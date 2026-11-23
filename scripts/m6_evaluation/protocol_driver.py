"""Run G0, G1, or G2 on one saved evidence bundle.

G2 calls the accepted generation pipeline. G0 and G1 do not reuse a dry run,
a no-repair review, or a G2 file with its review fields removed.
This module does not call the API unless generate=True is passed by the caller.
"""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import time

from scripts.m5_generation.api import M5Error, make_payload, read_key, strict_json
from scripts.m5_generation.batch import STOP_CODES, failed_pipeline, load_a_run
from scripts.m5_generation.billing import summarize_calls
from scripts.m5_generation.context import build_context
from scripts.m5_generation.generator import generate_answer
from scripts.m5_generation.m4_input import prepare_input
from scripts.m5_generation.pipeline import run_pipeline
from scripts.m5_generation.render import render_sources
from scripts.m5_generation.transport import request_with_retry
from scripts.m5_live.common import sha_file, write_json

ROOT = Path(__file__).resolve().parents[2]
G0_PROMPT = 'scripts/m5_generation/prompts/g0_prompt_citation_v1.txt'
G1_PROMPT = 'scripts/m5_generation/prompts/generation_v1.txt'
REPAIRABLE = {'INVALID_JSON', 'EMPTY_MODEL_OUTPUT', 'INCOMPLETE_RESPONSE',
              'INVALID_ANSWER_SCHEMA', 'CITATION_VALIDATION_FAILED', 'OUTPUT_LANGUAGE_MISMATCH'}


def file_sha256(path):
    return sha_file(path)


def prompt_sha256(relative):
    return file_sha256(ROOT / relative)


def binding(protocol, prompt, *, hard_validation, automatic_review, repair, max_repairs):
    return {
        'schema_version': 'm6_protocol.v1',
        'protocol': protocol,
        'prompt_file': prompt,
        'prompt_sha256': prompt_sha256(prompt),
        'hard_validation': hard_validation,
        'automatic_review': automatic_review,
        'repair': repair,
        'max_repairs': max_repairs,
        'driver': 'scripts/m6_evaluation/protocol_driver.py',
    }


def base_state(protocol, request_id):
    return {
        'schema_version': 'm5_pipeline.v1',
        'protocol': protocol,
        'status': 'ERROR',
        'gate': 'NOT_EVALUATED',
        'request_id': request_id,
        'publication_ready': False,
        'human_review': 'not_performed',
        'answer': '',
        'claims': [],
        'sources': [],
        'missing_information': [],
        'answer_record': None,
        'attempts': [],
        'repair_used': False,
        'api_calls': [],
        'error': None,
        'validation': {},
    }


def no_evidence(protocol, preview):
    state = base_state(protocol, preview.get('request_id'))
    state.update(status=preview['status'], gate='NO_RETRIEVAL_EVIDENCE', answer=preview['answer'],
                 missing_information=list(preview['missing_information']), answer_record=preview, error=None)
    state['protocol_binding'] = binding(protocol, G0_PROMPT if protocol == 'G0' else G1_PROMPT,
                                        hard_validation=False, automatic_review=False, repair=False, max_repairs=0)
    return state


def failed(protocol, request_id, error, gate, prompt, hard_validation):
    state = base_state(protocol, request_id)
    state.update(gate=gate, error=error)
    state['protocol_binding'] = binding(protocol, prompt, hard_validation=hard_validation,
                                        automatic_review=False, repair=False, max_repairs=0)
    return state


def g0_text(envelope):
    try:
        choice = envelope['choices'][0]
        content = choice['message']['content']
        finish = choice['finish_reason']
    except (KeyError, IndexError, TypeError):
        raise M5Error('INVALID_API_RESPONSE', 'Unexpected API response structure.') from None
    if finish != 'stop':
        raise M5Error('INCOMPLETE_RESPONSE', 'Model output did not finish normally.')
    if not isinstance(content, str) or not content.strip():
        raise M5Error('EMPTY_MODEL_OUTPUT', 'The model returned empty content. No automatic retry was made.')
    try:
        parsed = strict_json(content, source='model_content')
    except M5Error:
        return content.strip()
    if isinstance(parsed, dict) and isinstance(parsed.get('answer'), str) and parsed['answer'].strip():
        return parsed['answer'].strip()
    return content.strip()


def run_protocol_item(retrieval, protocol, *, dry_run=False, model='deepseek-flash',
                      key_provider=read_key, api_call=None, network_retries=0, pricing=None,
                      checkpoint=None):
    if protocol not in {'G0', 'G1', 'G2'}:
        raise M5Error('UNKNOWN_PROTOCOL', 'Protocol must be G0, G1, or G2.')
    if api_call is None:
        from scripts.m5_generation.api import call_api
        api_call = call_api
    if protocol == 'G2':
        state = run_pipeline(retrieval, dry_run=dry_run, model=model, allow_repair=True,
                             key_provider=key_provider, api_call=api_call, checkpoint=checkpoint,
                             network_retries=network_retries, pricing=pricing)
        state['protocol'] = 'G2'
        state['protocol_binding'] = binding('G2', G1_PROMPT, hard_validation='release_gate',
                                            automatic_review=True, repair=True, max_repairs=1)
        if checkpoint is not None:
            checkpoint(state)
        return state
    preview = generate_answer(retrieval, dry_run=True, model=model)
    request_id = preview.get('request_id')
    if preview['status'] == 'ERROR':
        return failed(protocol, request_id, preview['error'], 'ERROR',
                      G0_PROMPT if protocol == 'G0' else G1_PROMPT, protocol == 'G1')
    if preview['status'] == 'INSUFFICIENT_SOURCES':
        return no_evidence(protocol, preview)
    if dry_run:
        state = base_state(protocol, request_id)
        state.update(status='READY_FOR_PIPELINE', gate='NOT_RUN', preview=preview)
        return state
    state = base_state(protocol, request_id)
    state['evidence_chunk_ids'] = [item['chunk_id'] for item in preview['evidence']]
    prompt = G0_PROMPT if protocol == 'G0' else G1_PROMPT
    state['protocol_binding'] = binding(protocol, prompt,
                                        hard_validation='release_gate' if protocol == 'G1' else False,
                                        automatic_review=False, repair=False, max_repairs=0)
    cached_key = None

    def emit():
        if checkpoint is not None:
            checkpoint(state)

    def get_key():
        nonlocal cached_key
        if cached_key is None:
            cached_key = key_provider()
        return cached_key

    def transport(payload, key):
        if len(state['api_calls']) >= 1 + network_retries:
            raise M5Error('CALL_LIMIT', 'This protocol sends one generation and does not review or repair.')
        return request_with_retry(payload, key, api_call=api_call, ledger=state['api_calls'],
                                  stage='generation', logical_call=1, max_requests=1 + network_retries,
                                  retries=network_retries, emit=emit)

    try:
        if protocol == 'G0':
            prepared, _meta = prepare_input(retrieval)
            evidence, _excluded = build_context(prepared, model, _meta['selected_chunk_ids'])
            payload = make_payload(prepared['query'], evidence, model, system_prompt=(ROOT / G0_PROMPT).read_text(encoding='utf-8'))
            text = g0_text(transport(payload, get_key()))
            state.update(status='PROMPT_ANSWER', gate='PROMPT_CITATION_ONLY', answer=text, error=None,
                         validation={'schema': 'not_applicable', 'citation_ids': 'prompt_only', 'quote_match': 'not_applicable'})
            state['attempts'].append({'number': 1, 'generation': {'answer': text, 'validation': state['validation']}, 'review': None})
        else:
            generated = generate_answer(retrieval, model=model, repair_once=False,
                                        key_provider=get_key, api_call=transport)
            state['attempts'].append({'number': 1, 'generation': generated, 'review': None})
            if generated['status'] == 'ERROR':
                code = (generated.get('error') or {}).get('code')
                state.update(status='ERROR', answer='', claims=[], sources=[], missing_information=[],
                             answer_record=None, error=generated.get('error'),
                             gate='BLOCKED' if code in REPAIRABLE else 'ERROR')
            else:
                state.update(status=generated['status'], gate='HARD_VALIDATION_PASSED', answer=generated['answer'],
                             claims=generated['claims'], sources=generated['sources'],
                             missing_information=generated['missing_information'], answer_record=generated, error=None)
    except M5Error as exc:
        state.update(status='ERROR', gate='ERROR', answer='', error={'code': exc.code, 'message': str(exc)})
    except KeyboardInterrupt:
        for call in state['api_calls']:
            if call.get('state') == 'STARTING':
                call['state'] = 'INTERRUPTED_OUTCOME_UNKNOWN'
        state.update(status='ERROR', gate='ERROR', answer='', claims=[], sources=[], missing_information=[],
                     answer_record=None,
                     error={'code': 'CANCELLED', 'message': 'Run cancelled. An in-flight API request may still have used credit.'})
    finally:
        cached_key = None
        emit()
    return state


def comparison_plan(retrieval_run, model):
    path = Path(retrieval_run)
    results = path / 'results.jsonl'
    return {
        'protocols': ['G0', 'G1', 'G2'],
        'retrieval_run': str(path),
        'results_sha256': file_sha256(results) if results.is_file() else None,
        'model': model,
        'same_questions': True,
        'same_evidence': True,
        'same_model': True,
        'scoring_rubric': 'documents/m6/ANSWER_SCORING_v1.md',
        'generated': False,
        'official_scores': '0/0',
        'dry_run_is_protocol': False,
        'no_repair_is_g1': False,
        'strip_review_is_g1': False,
    }


def packed_request_id(packed):
    if isinstance(packed, dict) and isinstance(packed.get('retrieval'), dict):
        return packed['retrieval'].get('request_id')
    if isinstance(packed, dict):
        return packed.get('request_id')
    return None


def run_saved_protocol(retrieval_run, output_dir, protocol, *, generate=False, model='deepseek-flash',
                       max_items=15, network_retries=0, pricing=None, key_provider=read_key, api_call=None):
    if not generate:
        raise M5Error('PROTOCOL_NOT_GENERATED', 'A local precheck is not a G0, G1, or G2 result.')
    output = Path(output_dir).resolve()
    if output.exists():
        raise M5Error('OUTPUT_EXISTS', 'Choose a new output directory.')
    manifest, items = load_a_run(retrieval_run, max_items=max_items)
    output.mkdir(parents=True)
    started = time.perf_counter()
    run = {
        'schema_version': 'm6_protocol_run.v1', 'protocol': protocol, 'status': 'RUNNING',
        'request_count': len(items), 'completed_count': 0, 'api_requests': 0, 'model': model,
        'retrieval_run': str(Path(retrieval_run).resolve()), 'results_sha256': manifest.get('results_sha256'),
        'input_sha256': manifest.get('input_sha256'), 'gold_sent_to_model': False,
        'network_retries': network_retries, 'total_cost': None,
    }
    write_json(output / 'run.json', run)
    all_calls = []
    counts = Counter()
    stop_reason = None
    try:
        with (output / 'predictions.jsonl').open('x', encoding='utf-8') as stream:
            for index, item in enumerate(items, 1):
                folder = output / ('item_' + str(index).zfill(4))
                folder.mkdir()

                def checkpoint(pipeline, folder=folder, index=index):
                    write_json(folder / 'pipeline.json', pipeline)
                    run['active_item'] = index
                    run['api_requests'] = len(all_calls) + len(pipeline.get('api_calls') or [])
                    write_json(output / 'run.json', run)

                if stop_reason:
                    pipeline = failed_pipeline('BATCH_ABORTED',
                                              'An earlier credential, account or cancellation error stopped paid work.',
                                              packed_request_id(item['packed']))
                else:
                    pipeline = run_protocol_item(item['packed'], protocol, model=model, key_provider=key_provider,
                                                api_call=api_call, network_retries=network_retries, pricing=pricing,
                                                checkpoint=checkpoint)
                checkpoint(pipeline)
                all_calls.extend(deepcopy(pipeline.get('api_calls') or []))
                error = pipeline.get('error')
                if error and error.get('code') in STOP_CODES:
                    stop_reason = error['code']
                row = {
                    'schema_version': 'm5_b_prediction.v1', 'id': item['record']['id'], 'line': item['record']['line'],
                    'request_id': pipeline.get('request_id'), 'status': pipeline['status'], 'gate': pipeline['gate'],
                    'protocol': protocol, 'answer': pipeline['answer'], 'claims': pipeline['claims'],
                    'sources': pipeline['sources'], 'sources_text': render_sources(pipeline['sources']),
                    'missing_information': pipeline['missing_information'], 'error': error,
                    'publication_ready': False, 'human_review': 'not_performed',
                    'repair_used': bool(pipeline.get('repair_used')),
                    'pipeline_file': str((folder / 'pipeline.json').relative_to(output)),
                    'pipeline_sha256': file_sha256(folder / 'pipeline.json'),
                }
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
                stream.flush()
                counts[row['status']] += 1
                run.update(completed_count=index, status_counts=dict(counts), api_requests=len(all_calls),
                           billing=summarize_calls(all_calls, pricing, model))
                write_json(output / 'run.json', run)
            run['status'] = 'COMPLETED_WITH_ERRORS' if counts['ERROR'] else 'COMPLETE'
    except BaseException as exc:
        run['status'] = 'INTERRUPTED' if isinstance(exc, KeyboardInterrupt) else 'FAILED'
        run['error'] = {'code': 'BATCH_INTERRUPTED' if isinstance(exc, KeyboardInterrupt) else 'BATCH_EXECUTION_FAILED',
                        'message': 'Inspect saved item checkpoints before retrying; provider outcomes may be unknown.'}
        run['billing'] = None
        run['api_requests'] = None
        raise
    finally:
        run['active_item'] = None
        run['timing_ms'] = {'total': round((time.perf_counter() - started) * 1000, 2)}
        predictions = output / 'predictions.jsonl'
        if predictions.is_file():
            run['predictions_sha256'] = file_sha256(predictions)
        write_json(output / 'run.json', run)
    return run


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Plan or run one G0, G1, or G2 evaluation on a saved evidence bundle.')
    parser.add_argument('--protocol', choices=('G0', 'G1', 'G2'), required=True)
    parser.add_argument('--retrieval-run', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--model', default='deepseek-flash')
    parser.add_argument('--budget-profile', type=Path)
    parser.add_argument('--max-items', type=int, default=15)
    parser.add_argument('--network-retries', type=int, choices=(0, 1), default=0)
    parser.add_argument('--generate', action='store_true')
    args = parser.parse_args(argv)
    model = args.model
    if args.budget_profile:
        from scripts.m5_generation.token_budget import load_budget_profile
        model = load_budget_profile(args.budget_profile)['model']
    plan = comparison_plan(args.retrieval_run, model)
    if not args.generate:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        print('No protocol run was started.')
        return 0
    if args.output_dir is None:
        print('ERROR: PROTOCOL_OUTPUT_REQUIRED; choose a new --output-dir.')
        return 1
    try:
        result = run_saved_protocol(args.retrieval_run, args.output_dir, args.protocol, generate=True,
                                    model=model, max_items=args.max_items, network_retries=args.network_retries)
    except M5Error as exc:
        print('ERROR: ' + exc.code + '; ' + str(exc))
        return 1
    except KeyboardInterrupt:
        print('Interrupted. Inspect checkpoints before retrying: ' + str(args.output_dir))
        return 130
    print(result['protocol'] + ' status: ' + result['status'])
    print('Physical API requests: ' + str(result['api_requests']))
    return 0 if result['status'] == 'COMPLETE' else 1


if __name__ == '__main__':
    raise SystemExit(main())
