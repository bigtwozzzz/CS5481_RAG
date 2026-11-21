"""Validate and unpack saved M4 input. No retrieval or API calls occur here."""
from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path
from .api import M5Error


def require(condition, message):
    if not condition:
        raise M5Error('INVALID_RETRIEVAL', message)


def check_schema(value, schema, path='$'):
    """Only the keywords used by the delivered M4 v2 schema, not general JSON Schema.

    Unsupported keywords fail closed. Runtime consistency checks follow this check.
    """
    from .contracts import number, valid_utc
    known = {'$schema', 'type', 'additionalProperties', 'required', 'properties',
             'const', 'enum', 'minimum', 'maximum', 'minLength', 'pattern', 'format',
             'items', 'minItems', 'maxItems', 'uniqueItems', 'anyOf', 'allOf', 'if', 'then'}
    require(set(schema) <= known, 'Unsupported v2 schema keyword at ' + path)
    kinds = {'object': lambda x: isinstance(x, dict), 'array': lambda x: isinstance(x, list),
             'string': lambda x: isinstance(x, str), 'null': lambda x: x is None,
             'integer': lambda x: type(x) is int, 'number': number,
             'boolean': lambda x: type(x) is bool}
    if 'type' in schema:
        expected = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        require(all(t in kinds for t in expected), 'Unsupported schema type')
        require(any(kinds[t](value) for t in expected), 'Invalid type at ' + path)
    if 'const' in schema:
        require(value == schema['const'], 'Invalid constant at ' + path)
    if 'enum' in schema:
        require(value in schema['enum'], 'Invalid enum at ' + path)
    if number(value):
        require('minimum' not in schema or value >= schema['minimum'], 'Below minimum at ' + path)
        require('maximum' not in schema or value <= schema['maximum'], 'Above maximum at ' + path)
    if isinstance(value, str):
        require(len(value) >= schema.get('minLength', 0), 'String too short at ' + path)
        if 'pattern' in schema:
            require(re.search(schema['pattern'], value) is not None, 'Invalid string at ' + path)
        if 'format' in schema:
            require(schema['format'] in {'uri', 'date-time'}, 'Unsupported schema format')
            if schema['format'] == 'date-time':
                require(valid_utc(value), 'Invalid UTC date at ' + path)
            # URL syntax and domains are checked by validate_retrieval below.
    if isinstance(value, dict):
        require(set(schema.get('required', [])) <= set(value), 'Missing fields at ' + path)
        properties = schema.get('properties', {})
        if schema.get('additionalProperties') is False:
            require(set(value) <= set(properties), 'Unknown fields at ' + path)
        for key, child in properties.items():
            if key in value:
                check_schema(value[key], child, path + '.' + key)
    if isinstance(value, list):
        require(len(value) >= schema.get('minItems', 0), 'Too few items at ' + path)
        require('maxItems' not in schema or len(value) <= schema['maxItems'], 'Too many items at ' + path)
        if schema.get('uniqueItems'):
            require(len({json.dumps(v, sort_keys=True) for v in value}) == len(value), 'Duplicate items at ' + path)
        if 'items' in schema:
            for i, item in enumerate(value):
                check_schema(item, schema['items'], path + '[' + str(i) + ']')
    if 'anyOf' in schema:
        matched = False
        for candidate in schema['anyOf']:
            try:
                check_schema(value, candidate, path)
                matched = True
            except M5Error:
                pass
        require(matched, 'No schema alternative matches at ' + path)
    for child in schema.get('allOf', []):
        check_schema(value, child, path)
    if 'if' in schema:
        try:
            check_schema(value, schema['if'], path)
        except M5Error:
            pass
        else:
            check_schema(value, schema.get('then', {}), path)


def validate_v2(data):
    from .api import strict_json
    from .contracts import validate_retrieval
    schema_path = Path(__file__).resolve().parents[2] / 'schemas/retrieval_response.v2.schema.json'
    try:
        schema = strict_json(schema_path.read_text(encoding='utf-8-sig'))
    except OSError:
        raise M5Error('INVALID_RETRIEVAL', 'M4 v2 schema is missing. Install the M4 delivery first.') from None
    check_schema(data, schema)
    # v2 early errors may have empty queries, null index and config.mode only.
    # Preserve these values; do not invent retrieval parameters or a question.
    if data['status'] == 'ERROR':
        return data
    internal = deepcopy(data)
    internal['schema_version'] = 'retrieval_response.v1'
    validate_retrieval(internal)
    config = data['config']
    for row in data['results']:
        methods = set(row['retrieved_by'])
        require(config['mode'] == 'hybrid' or methods == {config['mode']}, 'Mode/provenance mismatch')
        require('bm25' in methods or row['scores']['bm25'] is None, 'Unexpected BM25 score')
        require(config['mode'] == 'hybrid' or row['scores']['rrf'] is None, 'Unexpected RRF score')
    filters = data['filters'] or {}
    if 'date_from_ts' in filters and 'date_to_ts' in filters:
        require(filters['date_from_ts'] < filters['date_to_ts'], 'Invalid date interval')
    return data


def prepare_input(value):
    from .contracts import validate_retrieval
    require(isinstance(value, dict), 'Input must be an M4 response or packed example object.')
    packed = 'retrieval' in value
    if packed:
        require(set(value) == {'retrieval', 'context', 'context_tokens', 'selected_chunk_ids'},
                'Packed example must contain retrieval, context, context_tokens and selected_chunk_ids.')
    retrieval = deepcopy(value['retrieval'] if packed else value)
    validate_retrieval(retrieval)
    meta = {'source_schema_version': retrieval['schema_version'],
            'input_kind': 'saved_packed_example' if packed else 'retrieval_response',
            'live_retrieval_executed': False,
            'input_object_sha256': hashlib.sha256(json.dumps(value, ensure_ascii=False,
                sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest(),
            'candidate_count': len(retrieval['results']), 'original_input': deepcopy(value)}
    if packed:
        ids = value['selected_chunk_ids']
        require(isinstance(ids, list) and all(isinstance(i, str) for i in ids), 'Invalid selected_chunk_ids')
        require(len(ids) == len(set(ids)), 'Duplicate selected_chunk_ids')
        rows = {r['chunk_id']: r for r in retrieval['results']}
        require(all(i in rows for i in ids), 'Selected chunk ID was not retrieved')
        require(ids == [r['chunk_id'] for r in retrieval['results'] if r['chunk_id'] in set(ids)],
                'Selected chunks must retain retrieval order')
        require(type(value['context_tokens']) is int and value['context_tokens'] >= 0,
                'context_tokens must be a nonnegative integer')
        expected = ''.join(f"[{i}] {rows[i]['citation']['title']}\n{rows[i]['citation']['url']}\n{rows[i]['text']}\n\n" for i in ids)
        require(value['context'] == expected, 'Packed context differs from selected evidence or metadata')
        meta.update(selected_chunk_ids=list(ids), reported_context_tokens=value['context_tokens'],
                    budget_tokenizer='M4 embedding tokenizer proxy; count not recomputed by M5',
                    generation_token_budget_verified=False)
    else:
        meta.update(selected_chunk_ids=[r['chunk_id'] for r in retrieval['results']],
                    selection='All returned candidates, subject to the M5 byte limit',
                    generation_token_budget_verified=False)
    return retrieval, meta
