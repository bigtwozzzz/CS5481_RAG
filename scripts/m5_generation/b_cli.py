"""B single/batch entry: reuse A retrieval and the bounded, reviewed M5 pipeline."""
import argparse
import os
from pathlib import Path
import sys
import uuid

from .api import M5Error,read_key,strict_json
from .batch import run_saved_batch,require,bounded_json
from .billing import validate_pricing
from scripts.m5_live.cli import run_process
from scripts.m5_live.common import write_json

ROOT=Path(__file__).resolve().parents[2]


def default_m4_python(root=ROOT):
    executable=Path('Scripts/python.exe') if os.name=='nt' else Path('bin/python')
    candidates=[root/'.venv_m4'/executable, root/'.venv'/executable]
    return next((path for path in candidates if path.is_file()),candidates[0])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--retrieval-run',type=Path,help='Replay one completed A batch with verified artifact hashes')
    source.add_argument('--question',help='One question: execute A retrieval first')
    source.add_argument('--input-jsonl',type=Path,help='Question JSONL: execute A retrieval first')
    parser.add_argument('--work-base',type=Path)
    parser.add_argument('--m4-python',type=Path,default=default_m4_python(),
                        help='M4 Python 3.11 interpreter; native .venv_m4 or existing .venv by default')
    parser.add_argument('--config',type=Path,default=ROOT/'configs/m4_m5.yaml')
    parser.add_argument('--packing-policy',choices=('legacy_break_v1','skip_continue_dedup_v1'),default='skip_continue_dedup_v1')
    parser.add_argument('--top-k',type=int,choices=(3,5,10),default=5)
    parser.add_argument('--max-items',type=int,default=10)
    parser.add_argument('--network-retries',type=int,choices=(0,1),default=1)
    parser.add_argument('--pricing-json',type=Path,help='Verified model/currency/cache rates; absent pricing leaves paid cost unknown')
    parser.add_argument('--budget-profile',type=Path,
                        help='Additional tokenizer budget profile. Does not replace the built-in deepseek-flash profile.')
    parser.add_argument('--output-dir',type=Path)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--generate',action='store_true',help='Enable paid calls; at most 4 logical / 8 physical requests per question')
    mode.add_argument('--dry-run',action='store_true',help='Default: local M5 checks only; live inputs still execute local M4 retrieval')
    args=parser.parse_args()
    run_dir=(args.output_dir or ROOT/'m5_runs'/('b_'+uuid.uuid4().hex)).resolve()
    try:
        require(not run_dir.exists(),'OUTPUT_EXISTS','Choose a new output directory; no automatic resume is allowed.')
        require(1<=args.max_items<=1000,'INVALID_BATCH_LIMIT','max-items must be 1..1000.')
        pricing=bounded_json(args.pricing_json) if args.pricing_json else None
        model='deepseek-flash'
        if args.budget_profile:
            from .token_budget import load_budget_profile
            profile=load_budget_profile(args.budget_profile)
            model=profile['model']
            print('Budget profile: '+profile['profile_version']+' model: '+model,flush=True)
        if pricing is not None:validate_pricing(pricing,model)
        if args.generate:
            read_key()  # Validate without logging; the pipeline reads it again only when needed.
            if pricing is None:print('Cost: UNKNOWN until a verified pricing file is supplied; actual usage will be saved.',flush=True)
        a_root=args.retrieval_run
        if a_root is None:
            require(args.work_base is not None,'WORK_BASE_REQUIRED','Live input requires --work-base.')
            from scripts.m4_retrieval.cli import load_requests,validate_config
            requests=load_requests(args.input_jsonl,args.question)
            require(len(requests)<=args.max_items,'INVALID_BATCH_SIZE','Input exceeds max-items; no retrieval or API call was made.')
            config=bounded_json(args.config)
            config.update(top_k=args.top_k,packing_policy=args.packing_policy)
            validate_config(config)
            run_dir.mkdir(parents=True,exist_ok=False)
            write_json(run_dir/'retrieval_config.json',config)
            a_root=run_dir/'retrieval'
            if args.input_jsonl:
                # Snapshot the exact input; malformed rows remain A errors.
                raw=args.input_jsonl.read_bytes()
                source_path=run_dir/'questions.jsonl';source_path.write_bytes(raw)
            else:
                import json
                source_path=run_dir/'questions.jsonl'
                source_path.write_text(json.dumps({'id':'single','question':args.question},ensure_ascii=False)+'\n',encoding='utf-8')
            env={k:v for k,v in os.environ.items() if k.upper() not in ('DEEPSEEK_API_KEY','OPENAI_API_KEY','M5_API_KEY')}
            env.update(PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1')
            require(args.m4_python.is_file(),'M4_PYTHON_NOT_FOUND','Select the M4 Python 3.11 interpreter with --m4-python.')
            command=[str(args.m4_python.resolve()),'-B','-X','utf8','-m','scripts.m4_retrieval.cli',
                     '--input-jsonl',str(source_path),'--config',str(run_dir/'retrieval_config.json'),
                     '--work-base',str(args.work_base.resolve()),'--output-dir',str(a_root)]
            code=run_process(command,stage='a_live_retrieval',cwd=ROOT,env=env,timeout=1800)
            require(code in (0,1) and (a_root/'run.json').is_file(),'LIVE_RETRIEVAL_FAILED','A did not produce a complete batch. Inspect retrieval records.')
            output=run_dir/'generation'
        else:
            output=run_dir
        result=run_saved_batch(a_root,output,generate=args.generate,network_retries=args.network_retries,
                              pricing=pricing,max_items=args.max_items,model=model)
        print('B batch status: '+result['status'])
        print('Physical API requests: '+str(result['api_requests']))
        print('Billing complete: '+str(result.get('billing',{}).get('complete',False)).lower())
        print('Batch record saved: '+str(output/'run.json'))
        print('Predictions saved: '+str(output/'predictions.jsonl'))
        print('Human review: not performed; publication_ready=false.')
        return 1 if result['status']=='COMPLETED_WITH_ERRORS' else 0
    except M5Error as exc:
        print('ERROR: '+exc.code+'; '+str(exc))
        return 1
    except KeyboardInterrupt:
        print('Interrupted. Inspect checkpoints before retrying: '+str(run_dir))
        return 130
    except Exception:
        print('ERROR: B_ENTRY_FAILED; inspect local inputs and checkpoints: '+str(run_dir))
        return 1


if __name__=='__main__':raise SystemExit(main())
