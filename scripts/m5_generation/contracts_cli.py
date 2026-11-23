"""Export and verify public contract views of a saved pipeline, without API calls."""
import argparse
import hashlib
import json
from pathlib import Path
import uuid

from .api import M5Error, strict_json
from .public_contracts import CONTRACTS, ROOT, export_pipeline_contracts, schema_validator


def main():
    parser=argparse.ArgumentParser(description='Offline M5 contract checks. A local PASS is not semantic approval.')
    parser.add_argument('--pipeline', required=True, type=Path, help='Existing pipeline.json to inspect without modifying it')
    parser.add_argument('--output-dir', type=Path, help='New export directory; existing directories are refused')
    args=parser.parse_args()
    output=args.output_dir or Path('m5_runs')/('contracts_'+uuid.uuid4().hex)
    try:
        if output.exists():
            raise M5Error('OUTPUT_EXISTS','Choose a new export directory; existing records will not be overwritten.')
        if args.pipeline.stat().st_size > 20_000_000:
            raise M5Error('INPUT_FILE_TOO_LARGE','Pipeline record exceeds 20 MB.')
        raw=args.pipeline.read_bytes()
        pipeline=strict_json(raw.decode('utf-8-sig'))
        for name in CONTRACTS:
            schema_validator(name)
        artifacts=export_pipeline_contracts(pipeline)
        summary={'schema_version':'m5_contract_export.v1','implementation_version':'m5-public-contracts-v0.6',
                 'local_contract_checks':'PASS','source_pipeline_status':pipeline['status'],
                 'source_pipeline_gate':pipeline.get('gate'),'source_pipeline_file':str(args.pipeline.resolve()),
                 'source_pipeline_sha256':hashlib.sha256(raw).hexdigest(),
                 'schemas':{name:hashlib.sha256((ROOT/'schemas'/(name+'.schema.json')).read_bytes()).hexdigest()
                            for name in CONTRACTS},'artifacts':[], 'new_api_calls':0,
                 'semantic_reassessment_performed':False,'human_review':'not_performed','publication_ready':False}
        output.mkdir(parents=True,exist_ok=False)
        for relative,data in artifacts.items():
            path=output/relative
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('x',encoding='utf-8') as stream:
                json.dump(data,stream,ensure_ascii=False,indent=2,allow_nan=False)
            summary['artifacts'].append({'path':relative,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        with (output/'summary.json').open('x',encoding='utf-8') as stream:
            json.dump(summary,stream,ensure_ascii=False,indent=2,allow_nan=False)
        print('Mode: offline public contract validation; no API calls.')
        print('Public schemas: 4 loaded successfully.')
        print('Local contract checks: PASS')
        print('Source pipeline status: '+pipeline['status'])
        print('Source pipeline gate: '+str(pipeline.get('gate')))
        print('Contract artifacts exported: '+str(len(artifacts)))
        print('New API calls: 0')
        print('No new semantic review or human approval was performed; publication_ready=false.')
        print('Contract report saved: '+str((output/'summary.json').resolve()))
        return 0
    except M5Error as exc:
        print('ERROR: '+exc.code+'; '+str(exc))
    except (OSError,UnicodeError,ValueError,KeyError,TypeError,RecursionError):
        print('ERROR: CONTRACT_IO_OR_STRUCTURE; Cannot read, validate or save this record. Inspect paths and record structure.')
    return 1


if __name__=='__main__':
    raise SystemExit(main())
