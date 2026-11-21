"""Offline public contracts over the existing M5 wire formats.

No API calls, generation, or implicit semantic approval occur in this module.
Use validate_answer for local checks; an automatic judge stays separately bound.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from .api import M5Error
from .contracts import validate_retrieval
from .m4_input import prepare_input
from .support import prepare_record, validate_review
from .validator import validate_draft

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ('evidence_bundle.v1', 'generation_draft.v1', 'validation_report.v1', 'answer_response.v1')


def require(value, message, code='CONTRACT_MISMATCH'):
    if not value:
        raise M5Error(code, message)


def object_hash(value):
    try:
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise M5Error('INVALID_CONTRACT_VALUE', 'Contract data must be finite UTF-8 JSON.') from None


@lru_cache(maxsize=4)
def schema_validator(name):
    require(name in CONTRACTS, 'Unknown public contract.', 'UNKNOWN_CONTRACT')
    try:
        from jsonschema import Draft202012Validator, FormatChecker
        from jsonschema.exceptions import SchemaError
    except ImportError:
        raise M5Error('CONTRACT_DEPENDENCY_MISSING',
                      'Run this offline command with .venv_m4, which already includes jsonschema, or install requirements-m5-contracts.txt.') from None
    try:
        schema = json.loads((ROOT/'schemas'/(name+'.schema.json')).read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema, format_checker=FormatChecker())
    except (OSError, ValueError, SchemaError):
        raise M5Error('CONTRACT_SCHEMA_LOAD_ERROR', 'Cannot read the public schema: '+name) from None


def validate_schema(name, value):
    object_hash(value)
    error = next(schema_validator(name).iter_errors(value), None)
    if error is not None:
        # Return a path/rule without echoing untrusted evidence or arbitrary values.
        path = '/'.join(str(part) for part in error.absolute_path) or '<root>'
        raise M5Error('CONTRACT_SCHEMA_ERROR', name+' failed at '+path+' (rule: '+str(error.validator)+').')
    return value


def validate_evidence_bundle(bundle):
    validate_schema('evidence_bundle.v1', bundle)
    evidence = bundle['evidence']
    require(len({e['source_id'] for e in evidence}) == len(evidence), 'Duplicate source label.')
    require([e['source_id'] for e in evidence] == ['S'+str(i) for i in range(1,len(evidence)+1)],
            'Source labels must follow evidence order.')
    ranks = [e['rank'] for e in evidence]
    require(ranks == sorted(set(ranks)), 'Evidence ranks must be unique and increasing.')
    if evidence:
        rows = [{**e, 'rank':i, 'retrieved_by':['saved_evidence'],
                 'scores':dict.fromkeys(['distance','similarity','bm25','rrf','rerank'])}
                for i,e in enumerate(evidence,1)]
        validate_retrieval({'schema_version':'retrieval_response.v1',
            'request_id':bundle['request_id'],'query':bundle['query'],'retrieval_query':bundle['query'],
            'status':'OK','index':bundle['index'],'config':{'mode':'contract_check','candidate_k':len(rows),'top_k':len(rows)},
            'filters':None,'results':rows,'timing_ms':dict.fromkeys(['encode','search','rerank','total'],0),
            'warnings':[],'error':None})
    excluded = [e['chunk_id'] for e in bundle['excluded_evidence']]
    require(len(excluded) == len(set(excluded)), 'Duplicate excluded chunk.')
    require(not set(excluded).intersection(e['chunk_id'] for e in evidence), 'Evidence is also marked excluded.')
    budget = bundle['token_budget']
    if budget is not None:
        required = budget['input_tokens_local'] + budget['output_tokens_reserved'] + budget['safety_margin_tokens']
        require(required == budget['total_tokens_reserved'], 'Stored token budget total is inconsistent.')
        require(budget['application_total_token_limit'] - required == budget['headroom_tokens'],
                'Stored token budget headroom is inconsistent.')
    return bundle


def evidence_bundle_from_record(record):
    require(isinstance(record,dict) and record.get('schema_version') in
            {'answer_response.v1','m5_evidence_preview.v1'}, 'Expected a saved M5 answer or evidence preview.')
    if record['schema_version'] == 'm5_evidence_preview.v1':
        require(record.get('status') == 'READY_FOR_GENERATION', 'Invalid evidence preview status.')
    else:
        validate_schema('answer_response.v1', record)
    evidence = deepcopy(record.get('evidence', []))
    status = 'ERROR' if record['status']=='ERROR' else ('READY' if evidence else 'NO_EVIDENCE')
    bundle = {'schema_version':'evidence_bundle.v1','request_id':record.get('request_id'),
              'query':record.get('query'),'status':status,'evidence':evidence,'index':deepcopy(record.get('index')),
              'excluded_evidence':deepcopy(record.get('excluded_evidence',[])),
              'token_budget':deepcopy(record.get('token_budget')),'source_record_sha256':object_hash(record),
              'evidence_scope':'selected_for_generation_not_proof_of_api_submission',
              'error':deepcopy(record.get('error')) if status=='ERROR' else None}
    validate_evidence_bundle(bundle)
    # Revalidate original M4 input when it was saved. This checks membership, not
    # external authenticity: hashes are consistency identifiers, not signatures.
    meta = record.get('m4_input')
    require(meta is None or isinstance(meta,dict), 'Invalid saved M4 provenance.')
    if meta and 'original_input' in meta:
        original = meta['original_input']
        require(object_hash(original) == meta.get('input_object_sha256'), 'Saved M4 input hash changed.')
        retrieval, prepared = prepare_input(original)
        require(record.get('query') == retrieval['query'] and record.get('request_id') == retrieval['request_id'],
                'Answer identity differs from the saved M4 input.')
        require(record.get('index') == retrieval['index'], 'Index differs from the saved M4 input.')
        selected = prepared['selected_chunk_ids']
        ids = [e['chunk_id'] for e in evidence]
        require(set(ids) <= set(selected), 'Evidence was not selected by the saved M4 input.')
        require(ids == [i for i in selected if i in set(ids)], 'Evidence order differs from M4 selection.')
        rows = {r['chunk_id']:r for r in retrieval['results']}
        for item in evidence:
            require(all(item[k] == rows[item['chunk_id']][k] for k in
                    ('rank','chunk_id','document_id','chunk_index','text','text_sha256','citation')),
                    'Evidence content or metadata differs from the saved M4 input.')
        if status == 'NO_EVIDENCE':
            require(retrieval['status']=='NO_EVIDENCE', 'No-evidence refusal does not match retrieval status.')
    return bundle


def draft_from_answer(answer):
    require(answer.get('status') in {'ANSWERED','PARTIAL','INSUFFICIENT_SOURCES'},
            'System errors do not contain a model draft.')
    draft = {'status':answer['status'], 'claims':[
        {k:deepcopy(c[k]) for k in ('text','source_ids','evidence_quotes')} for c in answer['claims']],
        'missing_information':deepcopy(answer['missing_information'])}
    validate_schema('generation_draft.v1', draft)
    return draft


def validate_answer(answer, *, evidence_bundle=None):
    """Hard validation only; success never declares semantic support."""
    validate_schema('answer_response.v1', answer)
    own = evidence_bundle_from_record(answer)
    if evidence_bundle is not None:
        validate_evidence_bundle(evidence_bundle)
        for field in ('request_id','query','index','evidence'):
            require(own[field] == evidence_bundle[field], 'Answer differs from trusted evidence bundle: '+field)
    if answer['status'] == 'ERROR':
        return {'decision':'LOCAL_CHECKS_PASSED','support':'not_applicable','answerability':'unchecked'}
    prepared = prepare_record(answer)
    if prepared is None:
        expected = 'The current retrieval returned no evidence to support an answer.'
        # Original Chinese v0.1 renderer is retained in historical files; this
        # public English delivery accepts the current deterministic refusal only.
        require(answer['answer'] == expected, 'No-evidence refusal text was changed.')
        require(answer['validation'].get('answerability') == 'no_retrieval_evidence',
                'No-evidence refusal must identify the local refusal rule.')
    else:
        validate_draft(draft_from_answer(answer), answer['evidence'], enforce_english=True)
        by_source = {e['source_id']:e for e in answer['evidence']}
        for source in answer['sources']:
            require(all(source[k] == v for k,v in by_source[source['source_id']].items()),
                    'Source metadata differs from selected evidence.')
        require([c['claim_id'] for c in answer['claims']] ==
                ['C'+str(i) for i in range(1,len(answer['claims'])+1)], 'Claim labels must be consecutive.')
        require(answer['publication_ready'] is False, 'A generated answer cannot be marked publication-ready.')
    return {'decision':'LOCAL_CHECKS_PASSED',
            'support':'unchecked' if answer['claims'] else 'not_applicable','answerability':'unchecked'}


def validation_report_from_review(answer, review=None):
    validate_answer(answer)
    report={'schema_version':'validation_report.v1','request_id':answer.get('request_id'),
            'answer_object_sha256':object_hash(answer),'decision':'NOT_RUN','method':'not_run',
            'human_review':'not_performed','publication_ready':False,
            'checks':{'support':'unchecked' if answer['claims'] else 'not_applicable','answer_scope':'unchecked'},
            'claim_reviews':[],'answer_review':None,'error':None,'source_review_sha256':None,'judge':None}
    if review is not None:
        require(isinstance(review,dict) and review.get('schema_version')=='m5_support_review.v1', 'Unknown saved review format.')
        require(review.get('input_object_sha256') == object_hash(answer), 'Review is not bound to this answer.', 'REVIEW_BINDING_ERROR')
        require(review.get('input_snapshot') == answer, 'Review snapshot differs from this answer.', 'REVIEW_BINDING_ERROR')
        require(review.get('request_id') == answer.get('request_id'), 'Review request identity differs.')
        require(review.get('human_review') == 'not_performed' and review.get('publication_ready') is False,
                'Automatic review must not claim human approval.')
        decision = review.get('decision')
        if decision in {'PASS','FAIL'}:
            require(review.get('method')=='llm_judge' and review.get('local_validation')=='pass' and review.get('error') is None,
                    'Invalid completed automatic review state.')
            require(isinstance(review.get('judge'),dict) and review['judge'].get('calls')==1,
                    'Completed reviewer must record its one invocation.')
            prepared = prepare_record(answer)
            require(prepared is not None, 'No-evidence deterministic refusal does not require a model verdict.')
            checked = validate_review({'claim_reviews':review.get('claim_reviews'),'answer_review':review.get('answer_review')}, prepared,
                require_scope=review['judge'].get('prompt_version') in {'m5-support-en-v0.10', 'm5-support-en-v0.10.1'})
            require(checked['decision']==decision and checked['checks']==review.get('checks'),
                    'Stored review decision or checks disagree with its individual verdicts.', 'REVIEW_DECISION_MISMATCH')
            report.update({k:deepcopy(checked[k]) for k in ('decision','checks','claim_reviews','answer_review')})
        elif decision == 'ERROR':
            require(isinstance(review.get('error'),dict), 'Review ERROR requires error details.')
            report.update(decision='ERROR',error=deepcopy(review['error']))
        elif decision in {'READY_FOR_REVIEW','NOT_APPLICABLE'}:
            require(review.get('method')=='local_check_only' and isinstance(review.get('judge'),dict) and review['judge'].get('calls')==0 and review.get('error') is None,
                    'Local-only review must have zero calls and no error.')
            if decision=='NOT_APPLICABLE':
                require(not answer.get('evidence'), 'Evidence-bearing answer cannot bypass review.')
                report['decision']='NOT_APPLICABLE'
        else:
            raise M5Error('INVALID_REVIEW_STATE','Unsupported saved review state.')
        report.update(method=review['method'],source_review_sha256=object_hash(review),judge=deepcopy(review.get('judge')))
    validate_schema('validation_report.v1', report)
    return report


def export_pipeline_contracts(pipeline):
    require(isinstance(pipeline,dict) and pipeline.get('schema_version')=='m5_pipeline.v1', 'Use a saved m5_pipeline.v1 record.')
    require(pipeline.get('status') in {'ANSWERED','PARTIAL','INSUFFICIENT_SOURCES','ERROR','READY_FOR_PIPELINE'},
            'Pipeline is incomplete or has an unknown state.')
    require(pipeline.get('publication_ready') is False, 'Pipeline must remain unpublished.')
    artifacts = {}
    attempts = pipeline.get('attempts',[])
    require(isinstance(attempts,list), 'Invalid pipeline attempts.')
    for i,attempt in enumerate(attempts,1):
        require(isinstance(attempt,dict) and isinstance(attempt.get('generation'),dict), 'Invalid generation attempt.')
        require(attempt.get('number') == i, 'Attempt numbering is inconsistent.')
        answer = attempt['generation']
        validate_answer(answer)
        prefix='attempt_'+str(i)+'/'
        artifacts[prefix+'answer.json']=deepcopy(answer)
        artifacts[prefix+'evidence_bundle.json']=evidence_bundle_from_record(answer)
        if answer['status']!='ERROR':
            artifacts[prefix+'generation_draft.json']=draft_from_answer(answer)
            artifacts[prefix+'validation_report.json']=validation_report_from_review(answer,attempt.get('review'))
        else:
            require(attempt.get('review') is None, 'Failed generation cannot have a review.')
    status=pipeline['status']
    if status == 'READY_FOR_PIPELINE':
        require(pipeline.get('gate')=='NOT_RUN' and not attempts and not pipeline.get('api_calls'), 'Invalid preflight state.')
        artifacts['evidence_bundle.json']=evidence_bundle_from_record(pipeline['preview'])
    elif status == 'ERROR':
        require(pipeline.get('gate') in {'ERROR','BLOCKED'} and not pipeline.get('answer_record') and
                pipeline.get('answer')=='' and pipeline.get('claims')==[] and pipeline.get('sources')==[],
                'Failed pipeline must not expose an answer.')
        final={'schema_version':'answer_response.v1','request_id':pipeline.get('request_id'),'status':'ERROR',
               'claims':[],'sources':[],'answer':'','missing_information':[],'review_required':False,
               'publication_ready':False,'validation':{'input':'unchecked','support':'not_applicable'},
               'generation':{'calls':deepcopy(pipeline.get('api_calls',[]))},'error':deepcopy(pipeline.get('error'))}
        validate_answer(final)
        artifacts['final_answer.json']=final
    else:
        final=pipeline.get('answer_record')
        require(isinstance(final,dict) and final.get('status')==status, 'Final answer state differs from pipeline.')
        validate_answer(final)
        for key in ('answer','claims','sources','missing_information'):
            require(pipeline.get(key)==final[key], 'Pipeline rendering differs from final answer: '+key)
        if pipeline.get('gate')=='AUTOMATIC_REVIEW_PASSED':
            require(bool(attempts), 'Automatic PASS requires an actual attempt.')
            last=attempts[-1]
            require(final==last['generation'], 'Accepted final answer differs from reviewed generation.')
            report=validation_report_from_review(last['generation'],last.get('review'))
            require(report['decision']=='PASS', 'Automatic gate requires a matching PASS report.')
            artifacts['validation_report.json']=report
        else:
            require(pipeline.get('gate')=='NO_RETRIEVAL_EVIDENCE' and status=='INSUFFICIENT_SOURCES' and
                    not attempts and not pipeline.get('api_calls') and not final['evidence'],
                    'Unknown final gate or invalid no-evidence refusal.')
            artifacts['validation_report.json']=validation_report_from_review(final)
        artifacts['final_answer.json']=deepcopy(final)
        artifacts['evidence_bundle.json']=evidence_bundle_from_record(final)
    return artifacts
