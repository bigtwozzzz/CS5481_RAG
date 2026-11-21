"""Separate model review of a saved answer. Not a human quality gold standard."""
import hashlib
import json
import re
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from .api import M5Error, call_api, parse_envelope, read_key
from .contracts import nonempty, validate_retrieval
from .token_budget import check_budget, observe_usage
from .validator import validate_draft, require_english_prose

PROMPT_VERSION = 'm5-support-en-v0.10.1'
PROMPT = (Path(__file__).parent / 'prompts/support_v1.txt').read_text(encoding='utf-8')
MAX_INPUT_BYTES = 24000


def require(condition, message, code='INVALID_SAVED_ANSWER'):
    if not condition:
        raise M5Error(code, message)


def prepare_record(record):
    """Recheck saved text, mappings, quote offsets and rendered answer before paying for review."""
    require(isinstance(record, dict), 'Input must be a saved answer object.')
    require(record.get('schema_version') == 'answer_response.v1', 'Use an answer_response.v1 record produced by the generation module.')
    require(nonempty(record.get('request_id')) and nonempty(record.get('query')), 'The record is missing a request ID or question.')
    status = record.get('status')
    require(isinstance(status, str) and status in {'ANSWERED', 'PARTIAL', 'INSUFFICIENT_SOURCES'},
            'Only ANSWERED, PARTIAL and INSUFFICIENT_SOURCES records can be reviewed; errors and previews are excluded.')
    require('error' in record and record['error'] is None, 'The record contains an error or has no error field.')
    evidence = record.get('evidence')
    require(isinstance(evidence, list), 'The record has no evidence list.')
    require(isinstance(record.get('claims'), list) and isinstance(record.get('sources'), list), 'claims and sources must be lists.')
    require(isinstance(record.get('missing_information'), list), 'missing_information must be a list.')
    require(all(nonempty(item) for item in record['missing_information']), 'Missing information entries must be nonempty strings.')
    if not evidence:
        require(status == 'INSUFFICIENT_SOURCES' and not record['claims'] and not record['sources'],
                'A record without evidence must not contain claims or sources.')
        require(bool(record['missing_information']), 'A refusal must explain what information is missing.')
        return None

    rows, seen = [], set()
    for rank, source in enumerate(evidence, 1):
        require(isinstance(source, dict), 'Each evidence item must be an object.')
        sid = source.get('source_id')
        require(isinstance(sid, str) and re.fullmatch(r'S[1-9][0-9]*', sid) is not None,
                'Invalid evidence ID format.')
        require(sid not in seen, 'Duplicate evidence ID.')
        seen.add(sid)
        rows.append({
            'rank': rank, 'chunk_id': source.get('chunk_id'), 'document_id': source.get('document_id'),
            'chunk_index': source.get('chunk_index'), 'text': source.get('text'),
            'text_sha256': source.get('text_sha256'), 'citation': source.get('citation'),
            'scores': dict.fromkeys(['distance', 'similarity', 'bm25', 'rrf', 'rerank']),
            'retrieved_by': ['saved_evidence'],
        })
    # This is validation of the saved evidence, never claimed to be a new retrieval.
    validate_retrieval({
        'schema_version': 'retrieval_response.v1', 'request_id': record['request_id'],
        'query': record['query'], 'retrieval_query': record.get('retrieval_query', record['query']),
        'status': 'OK', 'index': record.get('index'),
        'config': {'mode': 'saved_record_check', 'candidate_k': len(rows), 'top_k': len(rows)},
        'filters': None, 'results': rows,
        'timing_ms': dict.fromkeys(['encode', 'search', 'rerank', 'total'], 0), 'warnings': [], 'error': None,
    })
    draft_claims, claims_by_id = [], {}
    for claim in record['claims']:
        require(isinstance(claim, dict), 'Each claim must be an object.')
        require(set(claim) == {'claim_id', 'text', 'source_ids', 'evidence_quotes', 'located_quotes'},
                'Saved claim fields do not match this version.')
        cid = claim.get('claim_id')
        require(isinstance(cid, str) and re.fullmatch(r'C[1-9][0-9]*', cid) is not None,
                'Invalid claim ID format.')
        require(cid not in claims_by_id, 'Duplicate claim ID.')
        claims_by_id[cid] = claim
        draft_claims.append({key: claim[key] for key in ('text', 'source_ids', 'evidence_quotes')})
    checked = validate_draft({'status': status, 'claims': draft_claims,
                              'missing_information': record['missing_information']}, evidence)
    for saved, validated in zip(record['claims'], checked['claims']):
        require(saved['located_quotes'] == validated['located_quotes'], 'Saved quote offsets do not match the relocated quotes.')
    sources = record['sources']
    require(all(isinstance(source, dict) and nonempty(source.get('source_id')) for source in sources),
            'Invalid sources list.')
    require(len({source['source_id'] for source in sources}) == len(sources), 'Duplicate IDs in the sources list.')
    expected_sources = {source['source_id']: source for source in checked['sources']}
    require({source['source_id'] for source in sources} == set(expected_sources), 'The sources list does not match the cited sources.')
    for saved in sources:
        original = expected_sources[saved['source_id']]
        for field in ('chunk_id', 'document_id', 'text', 'text_sha256', 'citation'):
            require(saved.get(field) == original[field], 'Source list differs from evidence: ' + field)
        for field in ('url', 'title', 'published_at_utc'):
            require(saved.get(field) == original['citation'][field], 'Source display field was changed: ' + field)
    lines = [claim['text'] + ' ' + ''.join('[' + sid + ']' for sid in claim['source_ids'])
             for claim in record['claims']]
    # Preserve the renderer of existing v0.1 records, without rewriting historical output.
    prefix = ('\u8d44\u6599\u7f3a\u53e3\uff1a' if record.get('implementation_version') == 'm5-integration-v0.1'
              else 'Missing information: ')
    lines.extend(prefix + item for item in record['missing_information'])
    require(record.get('answer') == '\n'.join(lines), 'Rendered answer differs from the structured claims. Partial text review is not allowed.')
    return {
        'QUESTION': record['query'],
        'DRAFT': {'status': status, 'claims': [
            {key: claim[key] for key in ('claim_id', 'text', 'source_ids', 'evidence_quotes')}
            for claim in record['claims']], 'missing_information': record['missing_information']},
        'EVIDENCE': [{key: source[key] for key in ('source_id', 'chunk_id', 'document_id', 'text', 'citation')}
                     for source in evidence],
    }


def make_review_payload(prepared, model):
    content = json.dumps(prepared, ensure_ascii=False, allow_nan=False)
    require(len((PROMPT + content).encode('utf-8')) <= MAX_INPUT_BYTES,
            'Review input exceeds the temporary 24 KB limit. No truncation or API call was made.', 'REVIEW_INPUT_TOO_LARGE')
    payload = {'model': model, 'messages': [{'role': 'system', 'content': PROMPT},
            {'role': 'user', 'content': content}], 'response_format': {'type': 'json_object'},
            'thinking': {'type': 'disabled'}, 'temperature': 0, 'max_tokens': 2400, 'stream': False}

    check_budget(payload, error_code='REVIEW_TOKEN_BUDGET_EXCEEDED')
    return payload

def require_review_fields(value, expected, location):
    """Record bounded schema diagnostics, never model prose or arbitrary field names."""
    if isinstance(value, dict) and set(value) == expected:
        return
    known = {'claim_reviews', 'answer_review', 'claim_id', 'verdict', 'relevant',
             'reason', 'citation_reviews', 'source_id', 'scope_role', 'relevance_reason',
             'recommended_status', 'status_appropriate', 'missing_information_accurate',
             'no_unresolved_conflicts', 'decision', 'status', 'support', 'relevance'}
    keys = set(value) if isinstance(value, dict) else set()
    def safe_fields(names):
        return sorted(name for name in names if isinstance(name, str) and name in known)
    unexpected = keys - expected
    diagnostics = {
        'source': 'judge_output', 'reason': 'invalid_object_fields',
        'diagnostics_version': 'm5-review-shape-v0.10.1', 'location': location,
        'actual_type': type(value).__name__, 'expected_fields': sorted(expected),
        'received_known_fields': safe_fields(keys), 'missing_fields': sorted(expected - keys),
        'unexpected_known_fields': safe_fields(unexpected),
        'unexpected_field_count': len(unexpected),
        'unrecognized_field_count': len(keys - known),
        'content_values_saved': False}
    raise M5Error('INVALID_JUDGE_OUTPUT', 'Invalid review object fields at ' + location + '.', diagnostics)


def validate_review(review, prepared, *, require_scope=False):
    """Compute the final decision in code; the judge cannot add an overall pass flag."""
    def check(condition, message):
        require(condition, message, 'INVALID_JUDGE_OUTPUT')

    require_review_fields(review, {'claim_reviews', 'answer_review'}, '$')
    entries = review['claim_reviews']
    check(isinstance(entries, list), 'claim_reviews must be a list.')
    expected = {claim['claim_id']: claim for claim in prepared['DRAFT']['claims']}
    seen = set()
    for entry in entries:
        legacy_fields = {'claim_id', 'verdict', 'relevant', 'reason', 'citation_reviews'}
        scope_fields = {'scope_role', 'relevance_reason'}
        allowed = (legacy_fields | scope_fields,) if require_scope else (legacy_fields, legacy_fields | scope_fields)
        if not isinstance(entry, dict) or set(entry) not in allowed:
            require_review_fields(entry, legacy_fields | scope_fields if require_scope else legacy_fields,
                                  '$.claim_reviews[' + str(len(seen)) + ']')
        if scope_fields <= set(entry):
            role = entry['scope_role']
            check(isinstance(role, str) and role in {'direct_answer', 'essential_qualification', 'unnecessary'},
                  'Invalid scope role.')
            check(nonempty(entry['relevance_reason']), 'A separate relevance reason is required.')
            check(type(entry['relevant']) is bool and entry['relevant'] == (role != 'unnecessary'),
                  'Relevance contradicts the scope role.')
            require_english_prose([entry['relevance_reason']])
        cid = entry['claim_id']
        check(isinstance(cid, str) and cid in expected and cid not in seen, 'Missing, duplicate or unknown claim review ID.')
        seen.add(cid)
        check(isinstance(entry['verdict'], str) and entry['verdict'] in {'supported', 'unsupported', 'contradicted', 'uncertain'},
              'Unknown claim verdict.')
        check(type(entry['relevant']) is bool and nonempty(entry['reason']), 'Relevance must be a boolean with a nonempty reason.')
        citations = entry['citation_reviews']
        check(isinstance(citations, list), 'citation_reviews must be a list.')
        cited, expected_ids = set(), set(expected[cid]['source_ids'])
        for citation in citations:
            require_review_fields(citation, {'source_id', 'verdict', 'reason'},
                                  '$.claim_reviews.' + cid + '.citation_reviews[' + str(len(cited)) + ']')
            sid = citation['source_id']
            check(isinstance(sid, str) and sid in expected_ids and sid not in cited, 'Duplicate or unknown citation review source.')
            cited.add(sid)
            check(isinstance(citation['verdict'], str) and citation['verdict'] in {'supports', 'partial', 'unrelated', 'contradicts'},
                  'Unknown citation verdict.')
            check(nonempty(citation['reason']), 'Citation review requires a reason.')
        check(cited == expected_ids, 'Not all cited sources were reviewed.')
    check(seen == set(expected), 'Not all claims were reviewed.')

    answer = review['answer_review']
    require_review_fields(answer, {'recommended_status', 'status_appropriate',
          'missing_information_accurate', 'no_unresolved_conflicts', 'reason'}, '$.answer_review')
    for field in ('status_appropriate', 'missing_information_accurate', 'no_unresolved_conflicts'):
        check(type(answer[field]) is bool, 'Overall review flags must be booleans.')
    check(isinstance(answer['recommended_status'], str) and answer['recommended_status'] in
          {'ANSWERED', 'PARTIAL', 'INSUFFICIENT_SOURCES'}, 'Invalid recommended answer status.')
    check(nonempty(answer['reason']), 'Overall review requires a reason.')
    require_english_prose([answer['reason']] + [entry['reason'] for entry in entries] +
                         [c['reason'] for entry in entries for c in entry['citation_reviews']])
    support = all(entry['verdict'] == 'supported' and all(citation['verdict'] in {'supports', 'partial'}
                  for citation in entry['citation_reviews']) for entry in entries)
    relevant = all(entry['relevant'] for entry in entries)
    scope = (answer['status_appropriate'] and answer['missing_information_accurate']
             and answer['no_unresolved_conflicts']
             and answer['recommended_status'] == prepared['DRAFT']['status'])
    return {
        'decision': 'PASS' if support and relevant and scope else 'FAIL',
        'checks': {'support': ('pass' if support else 'fail') if entries else 'not_applicable',
                   'relevance': ('pass' if relevant else 'fail') if entries else 'not_applicable',
                   'answer_scope': 'pass' if scope else 'fail'},
        'claim_reviews': deepcopy(entries), 'answer_review': deepcopy(answer),
    }


def review_answer(record, *, dry_run=False, model='deepseek-flash', key_provider=read_key, api_call=call_api):
    started = time.perf_counter()
    result = {'schema_version': 'm5_support_review.v1', 'request_id': None,
              'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'decision': 'ERROR', 'method': 'llm_judge', 'human_review': 'not_performed',
              'review_required': True, 'publication_ready': False,
              'local_validation': 'unchecked', 'checks': {'support': 'unchecked', 'answer_scope': 'unchecked'},
              'judge': {'requested_model': model, 'returned_model': None, 'prompt_version': PROMPT_VERSION,
                        'temperature': 0, 'max_output_tokens': 2400, 'calls': 0,
                        'input_tokens': 0, 'output_tokens': 0, 'latency_ms': 0, 'cost_usd': None},
              'limitations': ['Automatic reviews can be wrong and do not replace human gold evaluation.',
                              'Separate calls to the same model are not independent reliable adjudication.',
                              'Official offline token counts are enforced locally; provider parity remains unverified.'], 'error': None}
    try:
        prepared = prepare_record(record)
        result['request_id'] = record['request_id']
        result['input_snapshot'] = deepcopy(record)
        result['input_object_sha256'] = hashlib.sha256(json.dumps(record, ensure_ascii=False,
            sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
        result['local_validation'] = 'pass'
        if prepared is None:
            result.update(decision='NOT_APPLICABLE', method='local_check_only')
            result['checks'] = {'support': 'not_applicable', 'answer_scope': 'unchecked'}
            return result
        payload = make_review_payload(prepared, model)
        result['token_budget'] = check_budget(payload)
        if dry_run:
            result.update(decision='READY_FOR_REVIEW', method='local_check_only')
            return result
        key = key_provider()
        result['judge'].update(calls=1, input_tokens=None, output_tokens=None)
        call_started = time.perf_counter()
        try:
            response = api_call(payload, key)
        finally:
            key = None
            result['judge']['latency_ms'] = round((time.perf_counter() - call_started) * 1000, 2)
        if isinstance(response, dict):
            result['judge']['returned_model'] = response.get('model')
            usage = response.get('usage')
            if isinstance(usage, dict):
                for local, remote in (('input_tokens', 'prompt_tokens'), ('output_tokens', 'completion_tokens')):
                    value = usage.get(remote)
                    if type(value) is int and value >= 0:
                        result['judge'][local] = value
        result['token_budget'] = observe_usage(result['token_budget'], result['judge']['input_tokens'])
        result.update(validate_review(parse_envelope(response), prepared, require_scope=True))
    except M5Error as exc:
        result.update(decision='ERROR', error={'code': exc.code, 'message': str(exc)})
        if exc.diagnostics is not None:
            result['error']['diagnostics'] = deepcopy(exc.diagnostics)
        if result['local_validation'] != 'pass':
            result['local_validation'] = 'fail'
    except (TypeError, ValueError, RecursionError):
        result.update(decision='ERROR', error={'code': 'INVALID_RECORD_VALUE', 'message': 'The input record contains unsupported values.'})
    finally:
        result['timing_ms'] = {'total': round((time.perf_counter() - started) * 1000, 2)}
    return result


def check_support(answer, **kwargs):
    """Public C interface. dry_run=True never calls the provider; all results remain drafts."""
    return review_answer(answer, **kwargs)
