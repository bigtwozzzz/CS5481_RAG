"""Consume a verified A run sequentially; no automatic resume of paid work."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from .api import M5Error, strict_json
from .pipeline import run_pipeline
from .public_contracts import export_pipeline_contracts
from .render import render_sources
from .billing import summarize_calls, validate_pricing
from scripts.m5_live.common import sha_file, write_json

STOP_CODES={'MISSING_API_KEY','INVALID_API_KEY','HTTP_401','HTTP_402','HTTP_403','CANCELLED'}


def require(value,code,message):
    if not value:raise M5Error(code,message)


def bounded_json(path,limit=20_000_000):
    require(path.is_file() and path.stat().st_size<=limit,'INVALID_INPUT_FILE','A required input file is missing or too large.')
    return strict_json(path.read_text(encoding='utf-8-sig'))


def bound_path(root,relative):
    require(isinstance(relative,str),'INVALID_A_RECORD','An A artifact path must be a string.')
    value=Path(relative)
    require(not value.is_absolute() and '..' not in value.parts,'INVALID_A_PATH','A artifact must use a relative path.')
    target=(root/value).resolve()
    require(target.is_relative_to(root.resolve()),'INVALID_A_PATH','A artifact path leaves the run directory.')
    return target


def load_a_run(root,max_items=10):
    root=Path(root).resolve()
    manifest=bounded_json(root/'run.json')
    require(manifest.get('schema_version')=='m4_adapter_run.v1' and manifest.get('mode')=='live_retrieval'
            and manifest.get('status') in ('COMPLETE','COMPLETED_WITH_ERRORS'),
            'INCOMPLETE_A_RUN','Use a completed live A batch, not check-only or interrupted output.')
    results=root/'results.jsonl'
    require(results.is_file() and results.stat().st_size<=5_000_000,'INVALID_A_RECORD','Missing or oversized results.jsonl.')
    require(sha_file(results)==manifest.get('results_sha256'),'A_HASH_MISMATCH','A results ledger differs from its manifest.')
    records=[strict_json(line) for line in results.read_text(encoding='utf-8').splitlines() if line.strip()]
    require(type(max_items) is int and 1<=max_items<=1000,'INVALID_BATCH_LIMIT','max-items must be 1..1000.')
    require(0<len(records)<=max_items and len(records)==manifest.get('request_count')==manifest.get('completed_count'),
            'INVALID_BATCH_SIZE','A record count is incomplete or exceeds the explicit max-items limit.')
    from .m4_input import prepare_input
    items=[];lines=set()
    for record in records:
        require(record.get('schema_version')=='m4_adapter_result.v1' and record.get('status') in ('OK','NO_EVIDENCE','ERROR'),
                'INVALID_A_RECORD','Unknown A result schema or status.')
        line=record.get('line')
        require(type(line) is int and line>0 and line not in lines,'INVALID_A_RECORD','Invalid or duplicate physical input line.')
        lines.add(line)
        packed=bound_path(root,record.get('packed_file'))
        audit=bound_path(root,record.get('packing_report_file'))
        require(sha_file(packed)==record.get('packed_sha256') and sha_file(audit)==record.get('packing_report_sha256'),
                'A_HASH_MISMATCH','An A evidence or audit file has changed.')
        value=bounded_json(packed,5_000_000); prepare_input(value)
        packing=bounded_json(audit)
        from scripts.m4_retrieval.packing import object_hash
        require(packing.get('packed_sha256')==object_hash(value) and packing.get('retrieval_sha256')==object_hash(value['retrieval']),
                'A_BINDING_MISMATCH','A packing audit is not bound to the supplied evidence.')
        require(record.get('request_id')==value['retrieval']['request_id'],'A_BINDING_MISMATCH','A request identity differs.')
        expected='ERROR' if packing.get('selection_status')=='EMPTY_SELECTED_CONTEXT' else value['retrieval']['status']
        require(record['status']==expected,'A_BINDING_MISMATCH','A result status differs from evidence.')
        if record['status']=='ERROR':
            expected_error='EMPTY_SELECTED_CONTEXT' if packing.get('selection_status')=='EMPTY_SELECTED_CONTEXT' else value['retrieval']['error']['code']
            require(isinstance(record.get('error'),dict) and record['error'].get('code')==expected_error,
                    'A_BINDING_MISMATCH','A error code differs from evidence.')
        items.append({'record':record,'packed':value})
    require(dict(Counter(x['record']['status'] for x in items))==manifest.get('status_counts'),
            'A_BINDING_MISMATCH','A status totals differ from its rows.')
    return manifest,items


def failed_pipeline(code,message,request_id=None):
    return {'schema_version':'m5_pipeline.v1','status':'ERROR','gate':'ERROR','request_id':request_id,
            'publication_ready':False,'human_review':'not_performed','answer':'','claims':[],'sources':[],
            'missing_information':[],'answer_record':None,'attempts':[],'api_calls':[],
            'repair_used':False,'error':{'code':code,'message':message}}


def run_saved_batch(a_root,output,*,generate=False,network_retries=1,pricing=None,max_items=10,
                    pipeline_fn=run_pipeline):
    require(type(network_retries) is int and network_retries in (0,1),'INVALID_RETRY_LIMIT','Network retries must be 0 or 1.')
    if pricing is not None:validate_pricing(pricing,'deepseek-flash')
    # Invalid metadata and hashes abort before any key access or billable operation.
    manifest,items=load_a_run(a_root,max_items)
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter()
    state={'schema_version':'m5_b_batch.v1','implementation_version':'m5-b-orchestration-v0.9',
           'created_at_utc':datetime.now(timezone.utc).isoformat(),'status':'RUNNING',
           'mode':'generate' if generate else 'dry_run','publication_ready':False,'human_review':'not_performed',
           'a_run_file':str((Path(a_root)/'run.json').resolve()),'a_run_sha256':sha_file(Path(a_root)/'run.json'),
           'a_input_sha256':manifest.get('input_sha256'),'retrieval_config':manifest['config'],
           'request_count':len(items),'completed_count':0,'max_api_requests':len(items)*4*(1+network_retries) if generate else 0,
           'api_requests':0,'network_retries_per_call':network_retries,'content_repairs_per_item':1,
           'pricing_snapshot':deepcopy(pricing),'results_file':'predictions.jsonl','automatic_resume':False,
           'code_sha256':{},'limitations':['Automatic review is not human verification.','Cost estimates are not invoices.',
              'A timeout or retry can incur unreported provider cost.','Historical A evidence is replayed unless live retrieval was explicitly requested.']}
    root=Path(__file__).resolve().parents[2]
    for rel in ('scripts/m5_generation/api.py','scripts/m5_generation/pipeline.py','scripts/m5_generation/batch.py',
                'scripts/m5_generation/transport.py','scripts/m5_generation/billing.py','scripts/m5_generation/render.py',
                'scripts/m5_generation/generator.py','scripts/m5_generation/support.py','scripts/m5_generation/validator.py',
                'scripts/m5_generation/public_contracts.py','scripts/m5_generation/token_budget.py',
                'scripts/m5_generation/prompts/generation_v1.txt','scripts/m5_generation/prompts/repair_v1.txt',
                'scripts/m5_generation/prompts/support_v1.txt'):
        state['code_sha256'][rel]=sha_file(root/rel)
    all_calls=[];counts=Counter();stop_reason=None
    write_json(output/'run.json',state)
    print('Batch mode: '+state['mode']+'; maximum physical API requests: '+str(state['max_api_requests']),flush=True)
    try:
        with (output/'predictions.jsonl').open('x',encoding='utf-8') as stream:
            for index,item in enumerate(items,1):
                folder=output/('item_'+str(index).zfill(4)); folder.mkdir()
                write_json(folder/'retrieval.json',item['packed'])
                def checkpoint(pipeline):
                    write_json(folder/'pipeline.json',pipeline)
                    state['active_item']=index
                    state['api_requests']=len(all_calls)+len(pipeline.get('api_calls',[]))
                    write_json(output/'run.json',state)
                if stop_reason:
                    pipeline=failed_pipeline('BATCH_ABORTED','An earlier credential, account or cancellation error stopped paid work.',item['packed']['retrieval']['request_id'])
                else:
                    pipeline=pipeline_fn(item['packed'],dry_run=not generate,network_retries=network_retries,
                                         pricing=pricing,checkpoint=checkpoint)
                checkpoint(pipeline)
                all_calls.extend(deepcopy(pipeline['api_calls']))
                contract_status='PASS'
                try:
                    artifacts=export_pipeline_contracts(pipeline)
                    for rel,value in artifacts.items():write_json(folder/'contracts'/rel,value)
                except M5Error:
                    contract_status='FAIL'
                    pipeline=failed_pipeline('PUBLIC_CONTRACT_CHECK_FAILED','The pipeline output failed public contracts.',pipeline.get('request_id'))
                    # Keep the original pipeline and its cost ledger for diagnosis.
                error=pipeline.get('error')
                if error and error['code'] in STOP_CODES:stop_reason=error['code']
                row={'schema_version':'m5_b_prediction.v1','id':item['record']['id'],'line':item['record']['line'],
                     'request_id':pipeline.get('request_id'),'status':pipeline['status'],'gate':pipeline['gate'],
                     'answer':pipeline['answer'],'claims':pipeline['claims'],'sources':pipeline['sources'],
                     'sources_text':render_sources(pipeline['sources']),'missing_information':pipeline['missing_information'],
                     'error':error,'upstream_error':pipeline.get('preview',{}).get('upstream_error'),
                     'publication_ready':False,'human_review':'not_performed','local_contract_checks':contract_status,
                     'repair_used':pipeline.get('repair_used',False),'pipeline_file':str((folder/'pipeline.json').relative_to(output)),
                     'pipeline_sha256':sha_file(folder/'pipeline.json')}
                stream.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n');stream.flush()
                counts[row['status']]+=1
                state.update(completed_count=index,status_counts=dict(counts),api_requests=len(all_calls),
                             billing=summarize_calls(all_calls,pricing,'deepseek-flash'))
                write_json(output/'run.json',state)
                print('Item '+str(index)+': '+row['status']+'; contracts: '+contract_status,flush=True)
            state['status']='COMPLETED_WITH_ERRORS' if counts['ERROR'] else 'COMPLETE'
    except BaseException as exc:
        state['status']='INTERRUPTED' if isinstance(exc,KeyboardInterrupt) else 'FAILED'
        state['error']={'code':'BATCH_INTERRUPTED' if isinstance(exc,KeyboardInterrupt) else 'BATCH_EXECUTION_FAILED',
                        'message':'Inspect saved item checkpoints before retrying; provider outcomes may be unknown.'}
        state['billing']=None  # A current item may have sent unaccounted requests.
        state['api_requests']=None
        raise
    finally:
        state['active_item']=None
        state['timing_ms']={'total':round((time.perf_counter()-started)*1000,2)}
        if (output/'predictions.jsonl').is_file():state['predictions_sha256']=sha_file(output/'predictions.jsonl')
        write_json(output/'run.json',state)
    return state
