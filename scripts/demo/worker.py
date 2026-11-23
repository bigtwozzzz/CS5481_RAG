"""Persistent M4 worker. JSON-lines on stdout; diagnostics on stderr, no secrets."""
import contextlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    workshop = None
    for line in sys.stdin:
        try:
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                if request['action'] == 'load':
                    from scripts.m5_live.common import inspect_paths
                    from scripts.m5_live.retrieval_worker import initialize
                    paths = inspect_paths(request['path'])
                    workshop = initialize(ROOT, paths, Path(request['run_dir']))
                    workshop.build_bm25()
                    documents = paths['data'] / 'data/documents/documents.jsonl'
                    with documents.open(encoding='utf-8') as stream:
                        count = sum(bool(line.strip()) for line in stream)
                    result = {'name': paths['base'].name, 'dir': str(paths['base']),
                              'docCount': count, 'embedModel': paths['manifests']['C']['embedding']['model'],
                              'indexStatus': 'Validated', 'collection': paths['manifests']['C']['vector_store']['collection']}
                elif request['action'] == 'retrieve' and workshop is not None:
                    from scripts.m4_retrieval.packing import pack_response
                    response = workshop.retrieve(request['question'], strategy='C', mode='hybrid',
                                                  top_k=5, candidate_k=30, rrf_constant=60)
                    packed, audit = pack_response(response, workshop.model.tokenizer, 1024,
                                                   'skip_continue_dedup_v1')
                    result = {'packed': packed, 'audit': audit}
                else:
                    raise ValueError('Knowledge base has not been loaded.')
            output = {'ok': True, 'result': result}
        except Exception as exc:
            output = {'ok': False, 'error': {'code': getattr(exc, 'code', 'RETRIEVAL_FAILED'),
                       'message': str(exc) if hasattr(exc, 'code') else 'Knowledge base validation or retrieval failed. Check the local runtime and index.'}}
        print(json.dumps(output, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
