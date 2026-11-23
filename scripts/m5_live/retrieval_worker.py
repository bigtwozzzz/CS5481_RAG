"""Load the pinned M4 runtime and save one Workshop v2 request. Never calls an LLM."""
import argparse
from copy import deepcopy
from contextlib import closing
from importlib.metadata import version
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

from .common import LiveError, inspect_paths, read_json, require, sha_file, write_json


def verify_distance(db_dir, name, metadata):
    with closing(sqlite3.connect((Path(db_dir)/'chroma.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
        row=db.execute('SELECT schema_str FROM collections WHERE name = ?', (name,)).fetchone()
    require(bool(row and row[0]), 'MISSING_VECTOR_SCHEMA', 'The persisted vector schema is missing.')
    index=json.loads(row[0]).get('keys',{}).get('#embedding',{}).get('float_list',{}).get('vector_index',{})
    require(index.get('enabled') is True and index.get('config',{}).get('space')=='cosine',
            'DISTANCE_MISMATCH', 'The active index must use cosine distance.')
    require(metadata.get('hnsw:space') in (None,'cosine'), 'DISTANCE_METADATA_CONFLICT', 'Conflicting distance metadata.')


def initialize(project, paths, run_dir):
    require(sys.version_info[:2]==(3,11),'M4_PYTHON_VERSION','M4 requires Python 3.11.')
    require(version('chromadb')=='1.5.9','M4_CHROMA_VERSION','M4 requires Chroma 1.5.9.')
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',
                      HF_HOME=str(paths['base']/'model_cache'),ANONYMIZED_TELEMETRY='False')
    import chromadb
    from chromadb.config import Settings
    import numpy as np
    from sentence_transformers import SentenceTransformer
    from scripts.m4_retrieval.retriever import Retriever
    from scripts.m4_retrieval.workshop import Workshop, make_schema

    manifests, manifest_paths=paths['manifests'],paths['manifest_paths']
    # Verify input files and persisted schemas before opening a writable runtime client.
    for strategy,m in manifests.items():
        chunk=paths['data']/m['input']['path']
        require(sha_file(chunk)==m['input']['sha256'],'CHUNK_HASH_MISMATCH','M3 chunk file hash mismatch.')
        with chunk.open(encoding='utf-8') as stream:
            count=sum(bool(line.strip()) for line in stream)
        require(count==m['chunk_count'],'CHUNK_COUNT_MISMATCH','M3 chunk count mismatch.')
        verify_distance(paths['db'],m['vector_store']['collection'],{})
    client=chromadb.PersistentClient(path=str(paths['db']),settings=Settings(anonymized_telemetry=False))
    collections={}
    for strategy,m in manifests.items():
        collection=client.get_collection(m['vector_store']['collection'],embedding_function=None)
        require(collection.count()==m['chunk_count'],'COLLECTION_COUNT_MISMATCH','Runtime collection count mismatch.')
        meta=collection.metadata or {}
        for field,expected in {'model_name':m['embedding']['model'],'model_revision':m['embedding']['revision'],
                               'embedding_dimension':384,'input_sha256':m['input']['sha256']}.items():
            require(meta.get(field)==expected,'COLLECTION_IDENTITY_MISMATCH','Runtime collection identity mismatch: '+field)
        verify_distance(paths['db'],collection.name,meta)
        saved=collection.get(limit=1,include=['embeddings'])
        vector=np.asarray(saved['embeddings'][0])
        require(vector.shape==(384,) and np.isfinite(vector).all() and np.isclose(np.linalg.norm(vector),1,atol=1e-4),
                'VECTOR_INVALID','Runtime vector dimension or normalization mismatch.')
        collections[strategy]=collection
        print(strategy+' index checks: PASS',flush=True)
    print('Loading the cached embedding model (offline).',flush=True)
    model=SentenceTransformer(str(paths['snapshot']),device='cpu',local_files_only=True,trust_remote_code=False)
    probe=model.encode(['startup check'],normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False)
    require(probe.shape==(1,384) and np.isfinite(probe).all() and np.isclose(np.linalg.norm(probe[0]),1,atol=1e-4),
            'MODEL_VECTOR_INVALID','Embedding model startup probe failed.')

    class LiveWorkshop(Workshop):
        """Reuse retrieval/packing; avoid the notebook constructor's schema rewrite."""
        def __init__(self, baseline):
            self.baseline=baseline
            self.model=baseline.model
            self.collections=dict(baseline.collections)
            self.manifests=deepcopy(baseline.manifests)
            self.manifest_paths=dict(baseline.manifest_paths)
            self.project_root,self.data_root,self.base=project,paths['data'],run_dir
            self.output=run_dir/'unused_workshop_output'
            self.schema_path=project/'schemas/retrieval_response.v2.schema.json'
            self.schema=make_schema(read_json(project/'schemas/retrieval_response.schema.json'))
            require(read_json(self.schema_path)==self.schema,'M4_SCHEMA_MISMATCH','Installed M4 schemas do not agree.')
            self.rows,self.by_id,self.lexical,self.docs={},{},{},{}
            self.dates_ready=False
            self.qa_path=project/'data/evaluation/qa_reviewed.json'
            self.validate_startup()

    workshop=LiveWorkshop(Retriever(model,collections,manifests,manifest_paths))
    workshop.load_corpus()
    return workshop


def retrieve_packed(workshop, question, config):
    from scripts.m4_retrieval.workshop import validate
    if config['mode'] in ('bm25', 'hybrid'):
        # Every worker starts fresh; notebook verification previously prepared this index.
        workshop.build_bm25()
    response=workshop.retrieve(question,strategy=config['strategy'],mode=config['mode'],top_k=config['top_k'],
                              candidate_k=config['candidate_k'],rrf_constant=config['rrf_constant'])
    validate(response,workshop.schema)
    if response['status']=='ERROR':
        return {'retrieval':response,'context':'','context_tokens':0,'selected_chunk_ids':[]}
    selected,context,used=workshop.pack(response['results'],token_budget=config['context_tokens'])
    return {'retrieval':response,'context':context,'context_tokens':used,'selected_chunk_ids':[r['chunk_id'] for r in selected]}


def main():
    parser=argparse.ArgumentParser(description='Internal offline M4 worker; no LLM API calls.')
    parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    project=Path(__file__).resolve().parents[2]
    start=time.perf_counter()
    startup={'schema_version':'m5_live_startup.v1','status':'STARTING','model_download_allowed':False,'api_calls':0}
    startup_path=args.output.parent/'m4_startup.json'
    try:
        require(not args.output.exists() and not startup_path.exists(),'OUTPUT_EXISTS','Worker outputs already exist.')
        request=read_json(args.request)
        paths=inspect_paths(request['work_base'],request['data_root'],request['run_db'])
        write_json(startup_path,startup)
        workshop=initialize(project,paths,args.output.parent)
        packed=retrieve_packed(workshop,request['question'],request['retrieval_config'])
        # The same boundary validator used by M5 rejects any malformed wrapper.
        from scripts.m5_generation.m4_input import prepare_input
        prepare_input(packed)
        write_json(args.output,packed)
        startup.update(status='PASS',live_retrieval_completed=True,
            retrieval_status=packed['retrieval']['status'],retrieval_file_sha256=sha_file(args.output),
            manifest_sha256={k:sha_file(p) for k,p in paths['manifest_paths'].items()},
            python=sys.version.split()[0],executable=sys.executable,model_snapshot=str(paths['snapshot']),
            elapsed_seconds=round(time.perf_counter()-start,3))
        write_json(startup_path,startup)
        print('Live retrieval status: '+packed['retrieval']['status'],flush=True)
        if packed['retrieval']['status']=='ERROR':
            error=packed['retrieval']['error']
            print('M4 error: '+error['code']+'; '+error['message'],flush=True)
        print('Retrieved candidates: '+str(len(packed['retrieval']['results'])),flush=True)
        print('Selected evidence items: '+str(len(packed['selected_chunk_ids'])),flush=True)
        return 0
    except Exception as exc:
        code=exc.code if isinstance(exc,LiveError) else 'M4_STARTUP_OR_RETRIEVAL_FAILED'
        startup.update(status='ERROR',error={'code':code,'exception_type':type(exc).__name__,
            'message':str(exc) if isinstance(exc,LiveError) else 'M4 could not complete initialization or retrieval. Inspect the local data, runtime database and model cache.'})
        # Refuse to overwrite an existing prior worker record.
        if startup_path.exists() and startup.get('schema_version')=='m5_live_startup.v1' and code!='OUTPUT_EXISTS':
            write_json(startup_path,startup)
        print('ERROR: '+code+'. No LLM API call was made.',flush=True)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
