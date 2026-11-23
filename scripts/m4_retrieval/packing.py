"""Versioned whole-chunk packing. Does not change Workshop.pack or M4 v2."""
from copy import deepcopy
import hashlib
import json

from scripts.m5_generation.api import M5Error
from scripts.m5_generation.m4_input import prepare_input

POLICIES = ('legacy_break_v1', 'skip_continue_dedup_v1')


def object_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def render_block(row):
    return f"[{row['chunk_id']}] {row['citation']['title']}\n{row['citation']['url']}\n{row['text']}\n\n"


def pack_response(response, tokenizer, token_budget=1024, policy='legacy_break_v1'):
    """Return unchanged v2 data in the existing wrapper, plus a separate audit.

    New policy deduplicates identical text only within the same document and
    identical citation metadata. Independent sources and conflicting metadata
    remain visible. Duplicate chunk identities are invalid upstream responses.
    Counts include labels, titles, URLs and separators, without truncation.
    """
    if type(token_budget) is not int or not 1 <= token_budget <= 8192:
        raise M5Error('INVALID_CONTEXT_BUDGET', 'Context budget must be an integer from 1 to 8192.')
    if policy not in POLICIES:
        raise M5Error('INVALID_PACKING_POLICY', 'Unknown packing policy.')
    original, _ = prepare_input(response)
    if original['schema_version'] != 'retrieval_response.v2':
        raise M5Error('INVALID_RETRIEVAL', 'The A adapter requires an M4 v2 response.')

    def count(text):
        encoded = tokenizer(text, truncation=False, add_special_tokens=False, verbose=False)
        ids = encoded['input_ids']
        if not isinstance(ids, list):
            raise M5Error('INVALID_TOKENIZER_OUTPUT', 'Expected an unbatched list of token IDs.')
        return len(ids)

    context, used, ids, exclusions, offsets = '', 0, [], [], []
    seen, stopped, citation_by_document, conflicts = {}, False, {}, []
    for row in original['results']:
        cid = row['chunk_id']
        citation_hash = object_hash(row['citation'])
        previous = citation_by_document.setdefault(row['document_id'], citation_hash)
        if previous != citation_hash:
            conflicts.append({'chunk_id':cid, 'document_id':row['document_id'],
                'kind':'SOURCE_METADATA_CONFLICT', 'action':'preserved_for_downstream_review'})
        if stopped:
            exclusions.append({'chunk_id':cid, 'reason':'after_first_oversized_chunk'})
            continue
        identity = (row['document_id'], citation_hash, row['text_sha256'])
        if policy == 'skip_continue_dedup_v1' and identity in seen:
            exclusions.append({'chunk_id':cid, 'reason':'duplicate_text_same_source',
                               'kept_chunk_id':seen[identity]})
            continue
        block = render_block(row)
        proposed = count(context + block)
        if proposed > token_budget:
            exclusions.append({'chunk_id':cid, 'reason':'context_token_budget',
                               'candidate_context_tokens':proposed})
            stopped = policy == 'legacy_break_v1'
            continue
        text_start = len(context) + len(block) - len(row['text']) - 2
        offsets.append({'source_id':'S'+str(len(ids)+1), 'chunk_id':cid,
            'context_text_start':text_start, 'context_text_end':text_start+len(row['text']),
            'chunk_text_start':0, 'chunk_text_end':len(row['text'])})
        context += block
        used = proposed
        ids.append(cid)
        seen[identity] = cid
    # Empty context uses zero tokens with add_special_tokens=False.
    if original['status'] == 'OK':
        used = count(context)
    packed = {'retrieval':deepcopy(original), 'context':context,
              'context_tokens':used, 'selected_chunk_ids':ids}
    prepare_input(packed)
    report = {'schema_version':'m4_packing_audit.v1', 'packing_policy':policy,
        'retrieval_sha256':object_hash(original), 'packed_sha256':object_hash(packed),
        'input_status':original['status'], 'candidate_count':len(original['results']),
        'selected_count':len(ids), 'context_token_budget':token_budget, 'context_tokens':used,
        'tokenizer_role':'M4 embedding tokenizer; not the M5 generation tokenizer',
        'generation_budget_verified':False, 'truncation_used':False,
        'selection_status':('EMPTY_SELECTED_CONTEXT' if original['status']=='OK' and not ids else original['status']),
        'excluded':exclusions, 'source_metadata_conflicts':conflicts,
        'semantic_conflict_check':'not_performed', 'offset_unit':'Python Unicode code points; end exclusive',
        'source_mapping_scope':'M4 selection; M5 may remove a suffix to meet its own budget',
        'source_mapping':offsets}
    return packed, report
