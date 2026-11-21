"""One question, two interpreters, bounded M5 pipeline; dry-run by default."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from .common import LiveError, inspect_paths, read_json, require, sha_file, write_json

PROJECT = Path(__file__).resolve().parents[2]


def run_process(command, *, stage, cwd, env, timeout=None):
    """Argument lists only; never shell text, key arguments or captured key input."""
    print('Stage: '+stage,flush=True)
    child=subprocess.Popen(command,cwd=cwd,env=env,shell=False)
    started=time.monotonic()
    try:
        while True:
            remaining=None if timeout is None else timeout-(time.monotonic()-started)
            if remaining is not None and remaining<=0:
                raise LiveError('CHILD_TIMEOUT','The '+stage+' stage timed out. It was stopped without retry.')
            try:
                return child.wait(timeout=min(30,remaining) if remaining is not None else 30)
            except subprocess.TimeoutExpired:
                print('Still running: '+stage,flush=True)
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill();child.wait()


def parser():
    p=argparse.ArgumentParser(description='One-question M4/M5 entry. Default: live retrieval plus local checks, zero DeepSeek calls.')
    p.add_argument('--question',help='English question; passed through a JSON file, never shell interpolation')
    p.add_argument('--work-base',type=Path,required=True,help='Existing M4_work directory containing data, runtime_chroma and model_cache')
    p.add_argument('--data-root',type=Path)
    p.add_argument('--run-db',type=Path)
    p.add_argument('--m4-python',type=Path,default=PROJECT/'.venv_m4/Scripts/python.exe')
    p.add_argument('--m5-python',type=Path,default=PROJECT/'.venv/Scripts/python.exe')
    p.add_argument('--output-dir',type=Path,help='New directory only; defaults to m5_runs/live_<id>')
    mode=p.add_mutually_exclusive_group()
    mode.add_argument('--check-only',action='store_true',help='Inspect paths and Python dependencies; no live retrieval or API calls')
    mode.add_argument('--dry-run',action='store_true',help='Explicit default: live retrieval and M5 budget/contract checks, no API calls')
    mode.add_argument('--generate',action='store_true',help='Enable paid generation/review, at most 4 API calls, using DEEPSEEK_API_KEY from the environment')
    p.add_argument('--no-repair',action='store_true',help='With --generate: at most 2 API calls, no repair')
    p.add_argument('--strategy',choices=list('ABC'),default='C')
    p.add_argument('--mode',choices=['dense','bm25','hybrid'],default='hybrid')
    p.add_argument('--top-k',type=int,default=5)
    p.add_argument('--candidate-k',type=int,default=30)
    p.add_argument('--rrf-constant',type=int,default=60)
    p.add_argument('--context-tokens',type=int,default=1024,help='M4 embedding-tokenizer proxy; M5 separately checks its actual prompt budget')
    p.add_argument('--retrieval-timeout',type=int,default=600,help='Startup/retrieval deadline in seconds, 30..1800; no automatic retry')
    return p


def validate_options(args):
    require(args.check_only or isinstance(args.question,str) and bool(args.question.strip()),'EMPTY_QUERY','Provide a nonempty --question.')
    require(args.question is None or len(args.question.encode('utf-8'))<=8000,'QUERY_TOO_LARGE','Question exceeds 8000 UTF-8 bytes.')
    require(1<=args.top_k<=args.candidate_k<=1000 and args.rrf_constant>=1,'INVALID_RETRIEVAL_CONFIG',
            'Require 1 <= top-k <= candidate-k <= 1000 and a positive RRF constant.')
    require(1<=args.context_tokens<=8192,'INVALID_CONTEXT_BUDGET','M4 context budget must be between 1 and 8192.')
    require(30<=args.retrieval_timeout<=1800,'INVALID_TIMEOUT','Retrieval timeout must be between 30 and 1800 seconds.')
    for path in (args.m4_python,args.m5_python):
        require(path.is_file(),'PYTHON_NOT_FOUND','A selected Python executable is missing: '+str(path))
    return inspect_paths(args.work_base,args.data_root,args.run_db)


def execute(args, *, project=PROJECT, runner=run_process):
    paths=validate_options(args)
    run_dir=(args.output_dir or project/'m5_runs'/('live_'+uuid.uuid4().hex)).resolve()
    require(not run_dir.exists(),'OUTPUT_EXISTS','Choose a new run directory; existing records will not be overwritten.')
    run_dir.mkdir(parents=True,exist_ok=False)
    request={'schema_version':'m5_live_request.v1','question':args.question.strip() if args.question else None,
             'work_base':str(paths['base']),'data_root':str(paths['data']),'run_db':str(paths['db']),
             'retrieval_config':{'strategy':args.strategy,'mode':args.mode,'top_k':args.top_k,
                 'candidate_k':args.candidate_k,'rrf_constant':args.rrf_constant,'context_tokens':args.context_tokens}}
    write_json(run_dir/'request.json',request)
    state={'schema_version':'m5_live_run.v1','implementation_version':'m5-live-entry-v0.7',
           'created_at_utc':datetime.now(timezone.utc).isoformat(),'status':'STARTING','stage':'environment_checks',
           'mode':'check_only' if args.check_only else ('generate' if args.generate else 'dry_run'),
           'question':request['question'],'live_retrieval_completed':False,'api_calls':0,
           'publication_ready':False,'human_review':'not_performed','error':None,'files':{},
           'limitations':['Single-question entry; batch JSONL and M6 evaluation are not implemented here.',
               'Default Hybrid/C is a development-informed demonstration configuration.',
               'M4 packing stops at the first oversized block. It is not a new packing policy.',
               'No date-filter option or derived date index is provided.',
               'Automatic review is not human verification. Actual cost and provider tokenizer parity remain unverified.']}
    env={**os.environ,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1'}
    m4_env={k:v for k,v in env.items() if k not in ('DEEPSEEK_API_KEY','OPENAI_API_KEY')}
    m4_env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',
                  HF_HOME=str(paths['base']/'model_cache'),ANONYMIZED_TELEMETRY='False')

    def checkpoint():
        write_json(run_dir/'run.json',state)

    def child(python, module, options, stage, timeout=None):
        state['stage']=stage;checkpoint()
        return runner([str(python.resolve()),'-B','-X','utf8','-m',module,*map(str,options)],
                      stage=stage,cwd=project,env=m4_env if python==args.m4_python else env,timeout=timeout)

    def record_file(name,path):
        state['files'][name]={'path':str(path.resolve()),'sha256':sha_file(path)}

    checkpoint()
    print('Run directory: '+str(run_dir),flush=True)
    print('Mode: '+state['mode']+'. '+('Paid API calls enabled only after retrieval checks.' if args.generate else 'DeepSeek API calls: 0.'),flush=True)
    try:
        for role,python in [('m4',args.m4_python),('m5',args.m5_python)]:
            output=run_dir/(role+'_environment.json')
            code=child(python,'scripts.m5_live.probe',['--role',role,'--output',output],role+'_environment',60)
            require(code==0 and output.is_file(),'ENVIRONMENT_CHECK_FAILED','The '+role.upper()+' interpreter check failed.')
            report=read_json(output)
            require(report.get('status')=='PASS' and report.get('role')==role,'ENVIRONMENT_CHECK_FAILED','Unexpected environment report.')
            record_file(role+'_environment',output)
        if args.check_only:
            state.update(status='ENVIRONMENT_READY',stage='complete')
            checkpoint();return state
        retrieval_path=run_dir/'retrieval.json'
        code=child(args.m4_python,'scripts.m5_live.retrieval_worker',
                   ['--request',run_dir/'request.json','--output',retrieval_path],'live_retrieval',args.retrieval_timeout)
        require(code==0 and retrieval_path.is_file(),'LIVE_RETRIEVAL_FAILED','M4 did not produce a usable result. M5 generation was not started.')
        from scripts.m5_generation.m4_input import prepare_input
        wrapper=read_json(retrieval_path,5_000_000)
        require(isinstance(wrapper,dict) and isinstance(wrapper.get('retrieval'),dict) and
                wrapper['retrieval'].get('schema_version')=='retrieval_response.v2',
                'LIVE_SCHEMA_MISMATCH','Live retrieval must return a packed Workshop v2 response.')
        retrieval,meta=prepare_input(wrapper)
        require(retrieval['query']==request['question'],'QUERY_MISMATCH','Retrieved question differs from the request.')
        if retrieval['status']!='ERROR':
            expected_config={k:request['retrieval_config'][k] for k in ('mode','top_k','candidate_k','rrf_constant')}
            require(retrieval['config']==expected_config and retrieval['index']=={
                'strategy':args.strategy,'collection':paths['manifests'][args.strategy]['vector_store']['collection'],
                'manifest_sha256':sha_file(paths['manifest_paths'][args.strategy])},
                'RETRIEVAL_CONFIG_MISMATCH','M4 returned another retrieval configuration or index.')
        startup=read_json(run_dir/'m4_startup.json')
        require(startup.get('status')=='PASS' and startup.get('live_retrieval_completed') is True and
                startup.get('retrieval_file_sha256')==sha_file(retrieval_path),
                'RETRIEVAL_BINDING_ERROR','M4 startup provenance does not match the saved retrieval.')
        state.update(live_retrieval_completed=True,retrieval_status=retrieval['status'],
                     request_id=retrieval['request_id'],candidate_count=len(retrieval['results']),
                     selected_count=len(meta['selected_chunk_ids']))
        record_file('retrieval',retrieval_path);record_file('m4_startup',run_dir/'m4_startup.json')
        # Preserve a proper M4 ERROR in the existing pipeline, but force zero API calls.
        generate=args.generate and retrieval['status']!='ERROR'
        options=['--input',retrieval_path,'--output-dir',run_dir/'pipeline']
        if not generate:options.append('--dry-run')
        if args.no_repair:options.append('--no-repair')
        # Unknown until the child checkpoint is read; an interrupted API call may be billable.
        state['api_calls']=None if generate else 0
        code=child(args.m5_python,'scripts.m5_generation.pipeline_cli',options,'m5_pipeline')
        pipeline_path=run_dir/'pipeline/pipeline.json'
        require(pipeline_path.is_file(),'M5_RECORD_MISSING','M5 did not save a pipeline record. Do not retry paid runs blindly.')
        pipeline=read_json(pipeline_path)
        require(pipeline.get('schema_version')=='m5_pipeline.v1' and
                pipeline.get('input_file_sha256')==state['files']['retrieval']['sha256'] and
                pipeline.get('request_id')==retrieval['request_id'],
                'PIPELINE_BINDING_ERROR','The M5 record is not bound to this live retrieval.')
        require(isinstance(pipeline.get('api_calls'),list),'PIPELINE_INCOMPLETE','M5 has not saved a completed call ledger.')
        state['api_calls']=len(pipeline['api_calls'])
        state['pipeline_status']=pipeline.get('status');state['pipeline_gate']=pipeline.get('gate')
        record_file('pipeline',pipeline_path)
        require(generate or state['api_calls']==0,'UNEXPECTED_API_CALL','A local-only run recorded an API call.')
        require(code==(1 if pipeline.get('status')=='ERROR' else 0),'M5_PROCESS_FAILED',
                'The M5 process did not finish consistently with its record. Inspect its checkpoint before retrying.')
        code=child(args.m4_python,'scripts.m5_generation.contracts_cli',
                   ['--pipeline',pipeline_path,'--output-dir',run_dir/'contracts'],'public_contract_checks',60)
        require(code==0,'PUBLIC_CONTRACT_CHECK_FAILED','Public contract checks failed. Do not treat the draft as accepted.')
        summary_path=run_dir/'contracts/summary.json'
        summary=read_json(summary_path)
        require(summary.get('local_contract_checks')=='PASS' and summary.get('source_pipeline_sha256')==sha_file(pipeline_path),
                'CONTRACT_BINDING_ERROR','Contract export does not match this pipeline record.')
        record_file('contracts',summary_path)
        state.update(status=pipeline['status'],stage='complete',local_contract_checks='PASS',
                     contract_artifacts=len(summary['artifacts']),error=pipeline.get('error'))
        checkpoint()
    except KeyboardInterrupt:
        state.update(status='ERROR',error={'code':'CANCELLED','message':'Run interrupted. Inspect child checkpoints before retrying; API outcome may be unknown.'})
        checkpoint()
    except Exception as exc:
        state.update(status='ERROR',error={'code':exc.code if isinstance(exc,LiveError) else 'LIVE_ENTRY_FAILED',
            'message':str(exc) if isinstance(exc,LiveError) else 'The current stage failed. Inspect its records before retrying.',
            'exception_type':type(exc).__name__})
        checkpoint()
    return state


def main():
    args=parser().parse_args()
    try:
        result=execute(args)
        print('Unified status: '+result['status'])
        print('Live retrieval completed: '+str(result['live_retrieval_completed']).lower())
        print('DeepSeek API calls: '+('UNKNOWN; inspect pipeline checkpoints' if result['api_calls'] is None else str(result['api_calls'])))
        if result.get('local_contract_checks'):print('Local contract checks: '+result['local_contract_checks'])
        if result.get('error'):print('Error: '+result['error']['code']+'; '+result['error']['message'])
        print('Human review: not performed; publication_ready=false.')
        return 1 if result['status']=='ERROR' else 0
    except (LiveError,OSError,ValueError,KeyError) as exc:
        print('ERROR: '+(exc.code if isinstance(exc,LiveError) else 'LOCAL_SETUP_FAILED')+'; '+str(exc))
        return 1
    except Exception:
        print('ERROR: LOCAL_SETUP_FAILED; A local input or dependency could not be validated. No automatic retry was performed.')
        return 1


if __name__=='__main__':
    raise SystemExit(main())
