"""Single/batch M4 adapter; versioned packing, no generation and no paid APIs."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid

from scripts.m5_generation.api import M5Error, strict_json
from scripts.m5_generation.m4_input import prepare_input
from scripts.m5_live.common import inspect_paths, sha_file, write_json
from .packing import POLICIES, pack_response

ROOT = Path(__file__).resolve().parents[2]


def require(condition, code, message):
    if not condition:
        raise M5Error(code, message)


def validate_config(config):
    require(isinstance(config, dict) and set(config)=={'strategy','mode','top_k','candidate_k',
        'rrf_constant','context_tokens','packing_policy'}, 'INVALID_CONFIG', 'Invalid configuration fields.')
    require(config['strategy'] in ('A','B','C') and config['mode'] in ('dense','bm25','hybrid'),
            'INVALID_CONFIG', 'Unknown retrieval strategy or mode.')
    for key in ('top_k','candidate_k','rrf_constant','context_tokens'):
        require(type(config[key]) is int, 'INVALID_CONFIG', 'Configuration numbers must be integers.')
    require(1 <= config['top_k'] <= config['candidate_k'] <= 1000 and config['rrf_constant'] >= 1,
            'INVALID_CONFIG', 'Invalid retrieval limits.')
    require(1 <= config['context_tokens'] <= 8192 and config['packing_policy'] in POLICIES,
            'INVALID_CONFIG', 'Invalid packing configuration.')
    return config


def validate_request(value, seen):
    require(isinstance(value, dict), 'INVALID_REQUEST', 'Each JSONL line must be an object.')
    require(set(value) <= {'id','question','filters'}, 'UNSUPPORTED_REQUEST_FIELDS',
            'Only id, question and filters are accepted. Keep evaluation labels outside retrieval input.')
    qid = value.get('id')
    require(isinstance(qid,str) and 0 < len(qid.strip()) <= 120, 'INVALID_ID', 'A nonempty id is required.')
    require(qid not in seen, 'DUPLICATE_ID', 'Request IDs must be unique within the file.')
    seen.add(qid)
    question = value.get('question')
    require(isinstance(question,str) and bool(question.strip()), 'EMPTY_QUERY', 'Question must not be blank.')
    require(len(question.encode('utf-8'))<=8000, 'QUERY_TOO_LARGE', 'Question exceeds 8000 UTF-8 bytes.')
    filters = value.get('filters')
    require(filters is None or isinstance(filters,dict), 'INVALID_FILTER', 'filters must be an object or null.')
    if filters:
        date_filter = any('date' in key.lower() for key in filters)
        raise M5Error('UNSUPPORTED_DATE_FILTER' if date_filter else 'UNSUPPORTED_FILTER',
                     'This adapter does not support filters. No retrieval was performed; no filter was ignored.')
    return {'id':qid,'question':question.strip()}


def load_requests(path=None, question=None):
    if path is not None:
        require(path.stat().st_size <= 5_000_000, 'INPUT_TOO_LARGE', 'JSONL exceeds 5 MB.')
        lines = [(n,line) for n,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1) if line.strip()]
    else:
        lines = [(1,json.dumps({'id':'single','question':question}))]
    require(0 < len(lines) <= 1000, 'INVALID_BATCH_SIZE', 'Supply 1 to 1000 nonblank request lines.')
    items, seen = [], set()
    for n,line in lines:
        value = None
        try:
            value = strict_json(line)
            request = validate_request(value,seen)
            items.append({'line':n,'request':request,'error':None})
        except M5Error as exc:
            qid = value.get('id') if isinstance(value,dict) else None
            items.append({'line':n,'request':{'id':qid if isinstance(qid,str) and len(qid)<=120 else None},
                          'error':{'code':exc.code,'message':str(exc)}})
    return items


def error_response(code, message, question=''):
    return {'schema_version':'retrieval_response.v2','request_id':uuid.uuid4().hex,
        'query':question,'retrieval_query':question,'status':'ERROR','index':None,'config':{'mode':'dense'},
        'filters':None,'results':[],'warnings':[], 'error':{'code':code,'message':message},
        'timing_ms':dict.fromkeys(('encode','search','rerank','total'),0)}


def retrieve_one(workshop, question, config):
    if config['mode'] in ('bm25','hybrid'):
        workshop.build_bm25()
    response = workshop.retrieve(question, **{k:config[k] for k in
        ('strategy','mode','top_k','candidate_k','rrf_constant')})
    require(response['query']==question, 'QUERY_MISMATCH', 'M4 returned another question.')
    return pack_response(response, workshop.model.tokenizer, config['context_tokens'],config['packing_policy'])


def run_batch(items, config, output, workshop_factory=None, check_only=False, input_sha256=None):
    """Output folder must be new. Sequential records are flushed after every item.

    No resumption or automatic retry yet. Never treat a partially written batch
    as complete. A future B batch runner can consume each packed_file directly.
    """
    validate_config(config)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {'schema_version':'m4_adapter_run.v1','implementation_version':'m4-adapter-v0.8',
        'created_at_utc':datetime.now(timezone.utc).isoformat(),'status':'RUNNING','api_calls':0,
        'mode':'check_only' if check_only else 'live_retrieval', 'config':config,
        'input_sha256':input_sha256,'request_count':len(items),'completed_count':0,
        'filter_support':'none; requested filters are rejected explicitly',
        'generation_budget_verified':False, 'publication_ready':False,
        'code_sha256':{str(p.relative_to(ROOT)):sha_file(p) for p in
            [Path(__file__),Path(__file__).with_name('packing.py'),ROOT/'scripts/m4_retrieval/workshop.py',
             ROOT/'scripts/m5_live/retrieval_worker.py', ROOT/'schemas/retrieval_response.v2.schema.json']}}
    write_json(output/'run.json',manifest)
    workshop, startup_error = None, None
    counts = Counter()
    started = time.perf_counter()
    try:
        with (output/'results.jsonl').open('x',encoding='utf-8') as stream:
            for position,item in enumerate(items,1):
                request=item['request']; error=item['error']
                question=request.get('question','')
                record={'schema_version':'m4_adapter_result.v1','line':item['line'],'id':request['id'],
                    'status':'ERROR','error':error,'packed_file':None,'packing_report_file':None,
                    'live_retrieval_executed':False,'api_calls':0}
                if error is None and check_only:
                    record.update(status='READY_FOR_RETRIEVAL')
                elif not check_only:
                    if error is None:
                        try:
                            if startup_error:
                                raise M5Error(startup_error['code'],startup_error['message'])
                            if workshop is None:
                                try:
                                    workshop=workshop_factory()
                                except Exception:
                                    startup_error={'code':'M4_INITIALIZATION_FAILED',
                                        'message':'M4 initialization failed. Check the runtime paths, versions and cached assets.'}
                                    raise M5Error(startup_error['code'],startup_error['message']) from None
                            record['live_retrieval_executed']=True
                            packed,audit=retrieve_one(workshop,question,config)
                        except Exception as exc:
                            error={'code':exc.code if isinstance(exc,M5Error) else 'RETRIEVAL_FAILED',
                                   'message':str(exc) if isinstance(exc,M5Error) else 'Retrieval or packing failed.'}
                    if error is not None:
                        packed,audit=pack_response(error_response(error['code'],error['message'],question),
                            lambda text,**kw: {'input_ids':[]},config['context_tokens'],config['packing_policy'])
                    prepare_input(packed)
                    folder=output/('item_'+str(position).zfill(4))
                    write_json(folder/'retrieval.json',packed)
                    write_json(folder/'packing.json',audit)
                    if packed['retrieval']['status']=='ERROR':
                        status='ERROR'; error=packed['retrieval']['error']
                    elif audit['selection_status']=='EMPTY_SELECTED_CONTEXT':
                        status='ERROR'; error={'code':'EMPTY_SELECTED_CONTEXT',
                            'message':'Candidates exist but no complete chunk fits. This is not a knowledge refusal.'}
                    else:
                        status=packed['retrieval']['status']; error=None
                    record.update(status=status,error=error,
                        request_id=packed['retrieval']['request_id'],
                        packed_file=str((folder/'retrieval.json').relative_to(output)),
                        packed_sha256=sha_file(folder/'retrieval.json'),
                        packing_report_file=str((folder/'packing.json').relative_to(output)),
                        packing_report_sha256=sha_file(folder/'packing.json'))
                stream.write(json.dumps(record,ensure_ascii=False,allow_nan=False)+'\n'); stream.flush()
                counts[record['status']]+=1
                manifest['completed_count']=position
                write_json(output/'run.json',manifest)
                print('Item '+str(position)+': '+record['status'],flush=True)
        manifest.update(status='COMPLETED_WITH_ERRORS' if counts['ERROR'] else 'COMPLETE',
                        status_counts=dict(counts), results_sha256=sha_file(output/'results.jsonl'))
    except BaseException:
        manifest.update(status='INTERRUPTED',status_counts=dict(counts))
        raise
    finally:
        manifest['elapsed_seconds']=round(time.perf_counter()-started,3)
        write_json(output/'run.json',manifest)
    return manifest


def main():
    parser=argparse.ArgumentParser(description='M4 A adapter: sequential single/batch retrieval; zero LLM API calls.')
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--question')
    source.add_argument('--input-jsonl',type=Path)
    parser.add_argument('--config',type=Path,default=ROOT/'configs/m4_m5.yaml')
    parser.add_argument('--packing-policy',choices=POLICIES)
    parser.add_argument('--top-k',type=int)
    parser.add_argument('--context-tokens',type=int)
    parser.add_argument('--work-base',type=Path)
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args()
    try:
        config=strict_json(args.config.read_text(encoding='utf-8-sig'))
        for key in ('packing_policy','top_k','context_tokens'):
            value=getattr(args,key)
            if value is not None: config[key]=value
        validate_config(config)
        items=load_requests(args.input_jsonl,args.question)
        require(args.check_only or args.work_base is not None,'WORK_BASE_REQUIRED','Live retrieval requires --work-base.')
        output=(args.output_dir or ROOT/'m5_runs'/('a_batch_'+uuid.uuid4().hex)).resolve()
        require(not output.exists(),'OUTPUT_EXISTS','Choose a new output directory; previous records are never overwritten.')
        def factory():
            from scripts.m5_live.retrieval_worker import initialize
            return initialize(ROOT,inspect_paths(args.work_base),output)
        result=run_batch(items,config,output,workshop_factory=factory,check_only=args.check_only,
                         input_sha256=sha_file(args.input_jsonl) if args.input_jsonl else None)
        print('Batch status: '+result['status'])
        print('Packing policy: '+config['packing_policy'])
        print('DeepSeek API calls: 0')
        print('M5 generation tokenizer budget: NOT RUN; pass each packed file to the M5 preflight.')
        print('Run record saved: '+str(output/'run.json'))
        return 1 if result['status']=='COMPLETED_WITH_ERRORS' else 0
    except (M5Error,OSError,UnicodeError,ValueError,TypeError) as exc:
        print('ERROR: '+(exc.code if isinstance(exc,M5Error) else 'LOCAL_INPUT_ERROR')+'; '+
              (str(exc) if isinstance(exc,M5Error) else 'Cannot read inputs or write a new run directory.'))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
