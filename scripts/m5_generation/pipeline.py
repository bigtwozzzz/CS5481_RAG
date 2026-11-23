"""Bounded generation/review pipeline; automatic PASS never implies human approval."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import time

from .api import M5Error, call_api, read_key
from .generator import generate_answer
from .token_budget import check_budget, observe_usage
from .support import review_answer
from .billing import summarize_calls, validate_pricing
from .render import derived_status, render_body
from .transport import request_with_retry

REPAIRABLE_GENERATION = {'INVALID_JSON', 'EMPTY_MODEL_OUTPUT', 'INCOMPLETE_RESPONSE',
                        'INVALID_ANSWER_SCHEMA', 'CITATION_VALIDATION_FAILED', 'OUTPUT_LANGUAGE_MISMATCH'}


def run_pipeline(retrieval, *, dry_run=False, model='deepseek-flash',
                 allow_repair=True, key_provider=read_key, api_call=call_api,
                 checkpoint=None, network_retries=0, pricing=None, retry_sleep=time.sleep):
    started = time.perf_counter()
    frozen_input = deepcopy(retrieval)
    state = {'schema_version':'m5_pipeline.v1', 'implementation_version':'m5-b-orchestration-v0.9',
             'created_at_utc':datetime.now(timezone.utc).isoformat(),
             'status':'ERROR', 'gate':'NOT_EVALUATED', 'active_stage':None,
             'publication_ready':False, 'human_review':'not_performed',
             'output_language':'en', 'answer':'', 'claims':[], 'sources':[],
             'missing_information':[], 'answer_status':None, 'answer_record':None,
             'attempts':[], 'repair_used':False, 'max_repairs':1 if allow_repair else 0,
             'api_calls':[], 'logical_calls':0, 'max_logical_calls':4 if allow_repair else 2,
             'network_retries_per_call':network_retries,
             'max_api_calls':(4 if allow_repair else 2)*(1+network_retries),
             'error':None, 'limitations':[
                 'Model review can miss unsupported or unnecessary claims; it is not human verification.',
                 'Official offline token budgets are enforced; provider parity is not verified and API usage is authoritative.',
                 'This command consumes supplied M4 data and does not execute retrieval.',
                 'At most one shared repair is allowed for generation or semantic failures.']}
    cached_key = None

    def emit():
        if checkpoint is not None:
            checkpoint(deepcopy(state))

    def get_key():
        nonlocal cached_key
        if cached_key is None:
            cached_key = key_provider()
        return cached_key

    def transport(stage):
        def request(payload, key):
            if state['logical_calls'] >= state['max_logical_calls']:
                raise M5Error('CALL_LIMIT', 'The logical pipeline call limit was reached.')
            state['logical_calls'] += 1
            state['active_stage'] = stage
            return request_with_retry(payload, key, api_call=api_call, ledger=state['api_calls'],
                stage=stage, logical_call=state['logical_calls'], max_requests=state['max_api_calls'],
                retries=network_retries, emit=emit, sleep=retry_sleep)
        return request

    def fail(error, gate='ERROR'):
        state.update(status='ERROR', gate=gate, error=deepcopy(error), answer='',
                     claims=[], sources=[], missing_information=[], answer_record=None, answer_status=None)

    def accept(answer, gate):
        computed = derived_status(answer['claims'], answer['missing_information'])
        if computed != answer['status']:
            raise M5Error('FINAL_STATUS_MISMATCH', 'Final status disagrees with validated claims and information gaps.')
        if gate == 'AUTOMATIC_REVIEW_PASSED' and render_body(answer['claims'], answer['missing_information']) != answer['answer']:
            raise M5Error('FINAL_RENDER_MISMATCH', 'Final text differs from the reviewed structured claims.')
        state.update(status=answer['status'], answer_status=answer['status'], gate=gate,
                     answer=answer['answer'], claims=deepcopy(answer['claims']),
                     sources=deepcopy(answer['sources']), missing_information=list(answer['missing_information']),
                     answer_record=deepcopy(answer), error=None)
        # All pipeline outputs are drafts, including deterministic no-candidate refusals.
        state['answer_record']['publication_ready'] = False
        state['answer_record']['review_required'] = True

    try:
        if type(network_retries) is not int or network_retries not in (0,1):
            raise M5Error('INVALID_RETRY_LIMIT', 'Network retries must be 0 or 1 per logical request.')
        if pricing is not None:
            validate_pricing(pricing, model)
        # Preflight avoids asking for a key on invalid or empty input.
        preview = generate_answer(frozen_input, dry_run=True, model=model)
        state['preview'] = preview
        state['request_id'] = preview.get('request_id')
        if preview['status'] == 'ERROR':
            fail(preview['error'])
            return state
        if preview['status'] == 'INSUFFICIENT_SOURCES':
            accept(preview, 'NO_RETRIEVAL_EVIDENCE')
            return state
        state['evidence_chunk_ids'] = [e['chunk_id'] for e in preview['evidence']]
        state['evidence_object_sha256'] = hashlib.sha256(json.dumps(preview['evidence'],ensure_ascii=False,
            sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
        if dry_run:
            state.update(status='READY_FOR_PIPELINE', gate='NOT_RUN')
            return state
        feedback = None
        for index in range(2 if allow_repair else 1):
            if index:
                state['repair_used'] = True
            stage = 'repair_generation' if index else 'generation'
            state['active_stage'] = stage
            emit()
            generated = generate_answer(frozen_input, model=model, repair_once=False,
                revision_feedback=feedback, key_provider=get_key, api_call=transport(stage))
            attempt = {'number':index+1, 'generation':generated, 'review':None}
            state['attempts'].append(attempt)
            emit()
            if generated.get('evidence') != preview['evidence']:
                fail({'code':'EVIDENCE_CHANGED','message':'Evidence changed between attempts. Processing stopped.'})
                return state
            if generated['status'] == 'ERROR':
                code = generated['error']['code']
                if code in REPAIRABLE_GENERATION and index == 0 and allow_repair:
                    feedback = {'validation_error_code':code,
                                'instruction':'Regenerate a valid English answer from the unchanged evidence.'}
                    continue
                fail(generated['error'], 'BLOCKED' if code in REPAIRABLE_GENERATION else 'ERROR')
                return state
            stage = 'repair_review' if index else 'review'
            state['active_stage'] = stage
            emit()
            reviewed = review_answer(generated, model=model, key_provider=get_key, api_call=transport(stage))
            attempt['review'] = reviewed
            emit()
            if reviewed['decision'] == 'PASS':
                accept(generated, 'AUTOMATIC_REVIEW_PASSED')
                return state
            if reviewed['decision'] == 'ERROR':
                fail(reviewed['error'])
                return state
            if reviewed['decision'] != 'FAIL':
                fail({'code':'UNEXPECTED_REVIEW_STATE','message':'The reviewer did not return PASS, FAIL or ERROR.'})
                return state
            if index or not allow_repair:
                fail({'code':'REVIEW_REJECTED','message':'The draft failed review. No answer was released.'}, 'BLOCKED')
                return state
            feedback = {'previous_draft':{'status':generated['status'],
                        'claims':[{k:c[k] for k in ('text','source_ids','evidence_quotes')} for c in generated['claims']],
                        'missing_information':generated['missing_information']},
                        'claim_reviews':reviewed['claim_reviews'], 'answer_review':reviewed['answer_review']}
    except M5Error as exc:
        fail({'code':exc.code,'message':str(exc)})
    except KeyboardInterrupt:
        for call in state['api_calls']:
            if call['state'] == 'STARTING':
                call['state'] = 'INTERRUPTED_OUTCOME_UNKNOWN'
        fail({'code':'CANCELLED','message':'Run cancelled. An in-flight API request may still have used credit.'})
    finally:
        cached_key = None
        state['active_stage'] = None
        calls = state['api_calls']
        state['usage'] = {field:sum(c[field] for c in calls) if all(c[field] is not None for c in calls) else None
                          for field in ('input_tokens','output_tokens')}
        state['usage']['complete'] = all(state['usage'][k] is not None for k in ('input_tokens','output_tokens'))
        state['billing'] = summarize_calls(calls, pricing, model)
        state['usage']['cost_usd'] = state['billing']['total_cost'] if state['billing']['currency']=='USD' else None
        state['network_retry_count'] = sum(c.get('network_attempt',1)>1 for c in calls)
        state['timing_ms'] = {'total':round((time.perf_counter()-started)*1000,2)}
        emit()
    return state
