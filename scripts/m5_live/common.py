"""Standard-library helpers; no models, credentials or network access on import."""
import hashlib
import json
import os
from pathlib import Path
import uuid

ARCHIVE_SHA = '89776eabda1e3dd4b1db8f096b970c0fb156357b40017dc8f78c49178f3ff586'
MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'


class LiveError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def require(condition, code, message):
    if not condition:
        raise LiveError(code, message)


def read_json(path, limit=20_000_000):
    from scripts.m5_generation.api import strict_json
    path = Path(path)
    require(path.stat().st_size <= limit, 'FILE_TOO_LARGE', 'Saved JSON exceeds its input limit.')
    return strict_json(path.read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temp.open('x', encoding='utf-8') as stream:
        stream.write(text + '\n')
    os.replace(temp, path)


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def inspect_paths(work_base, data_root=None, run_db=None):
    base = Path(work_base).resolve()
    data = Path(data_root).resolve() if data_root else base/'m3_data'
    db = Path(run_db).resolve() if run_db else base/'runtime_chroma'
    require(data.is_dir(), 'M3_DATA_MISSING', 'The extracted M3 data directory is missing.')
    require((data/'data/documents/documents.jsonl').is_file(), 'DOCUMENTS_MISSING', 'The M3 document file is missing.')
    require(db.is_dir() and (db/'chroma.sqlite3').is_file(), 'RUNTIME_DB_MISSING',
            'Use the existing initialized M4 runtime database; this command does not create or copy databases.')
    marker = db/'.m4_copy_ready.json'
    require(marker.is_file() and read_json(marker).get('archive_sha256') == ARCHIVE_SHA,
            'DB_MARKER_MISMATCH', 'The runtime database readiness marker is missing or belongs to another archive.')
    require(db != (data/'data/vector_store/chroma').resolve(), 'SOURCE_DB_NOT_ALLOWED',
            'Select the initialized runtime copy, not the original M3 database.')
    snapshot = base/'model_cache'/('models--'+MODEL.replace('/','--'))/'snapshots'/REVISION
    require(snapshot.is_dir() and (snapshot/'config.json').is_file(), 'MODEL_CACHE_MISSING',
            'The exact M4 model snapshot is not cached under the selected work base. No download was attempted.')
    manifests, paths = {}, {}
    for strategy in 'ABC':
        found = list((data/'data/vector_store/manifests').glob('chunks_'+strategy.lower()+'_*.manifest.json'))
        require(len(found)==1, 'MANIFEST_AMBIGUOUS', 'Exactly one M3 manifest per strategy is required.')
        m = read_json(found[0])
        expected = {'backend':'sentence-transformers','model':MODEL,'revision':REVISION,'dimension':384,'normalization':'L2'}
        require(m.get('schema_version')=='embedding_index.manifest.v1' and m.get('embedding')==expected and
                m.get('input',{}).get('strategy')==strategy and m.get('vector_store',{}).get('distance')=='cosine',
                'MANIFEST_PROFILE_MISMATCH', 'The M3 index does not match the reviewed model/profile.')
        chunk = (data/m['input']['path']).resolve()
        require(chunk.is_relative_to(data) and chunk.is_file(), 'CHUNK_PATH_INVALID', 'Missing or unsafe manifest chunk path.')
        manifests[strategy], paths[strategy] = m, found[0]
    return {'base':base,'data':data,'db':db,'snapshot':snapshot,'manifests':manifests,'manifest_paths':paths}
