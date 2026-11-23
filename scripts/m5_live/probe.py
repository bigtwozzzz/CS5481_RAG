"""Check the selected interpreter without loading the M4 embedding model."""
import argparse
from importlib.metadata import version
import sys
from .common import LiveError, require, write_json


def check_role(role):
    result={'role':role,'python':sys.version.split()[0],'executable':sys.executable,'packages':{}}
    if role=='m4':
        require(sys.version_info[:2]==(3,11), 'M4_PYTHON_VERSION', 'M4 requires the existing Python 3.11 environment.')
        for package in ('chromadb','sentence-transformers','numpy','jsonschema','tokenizers'):
            result['packages'][package]=version(package)
        require(result['packages']['chromadb']=='1.5.9', 'M4_CHROMA_VERSION', 'This runtime adapter requires Chroma 1.5.9.')
        from scripts.m5_generation.public_contracts import CONTRACTS, schema_validator
        for name in CONTRACTS:
            schema_validator(name)
    else:
        from scripts.m5_generation.token_budget import load_tokenizer, TOKENIZERS_VERSION
        result['packages']['tokenizers']=version('tokenizers')
        require(result['packages']['tokenizers']==TOKENIZERS_VERSION,'M5_TOKENIZER_VERSION','M5 requires tokenizers 0.22.2.')
        load_tokenizer()
    result.update(status='PASS',api_calls=0,embedding_model_loaded=False)
    return result


def main():
    parser=argparse.ArgumentParser(description='Offline interpreter check; no model downloads or API calls.')
    parser.add_argument('--role',choices=['m4','m5'],required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    try:
        result=check_role(args.role)
        write_json(args.output,result)
        print(args.role.upper()+' environment: PASS',flush=True)
        return 0
    except Exception as exc:
        code=exc.code if isinstance(exc,LiveError) else 'ENVIRONMENT_CHECK_FAILED'
        write_json(args.output,{'role':args.role,'status':'ERROR','error':{'code':code,
            'message':'Required interpreter, dependency or local assets are unavailable.'}})
        print('ERROR: '+code+'. Inspect the selected Python environment; no packages were changed.',flush=True)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
