from copy import deepcopy
from .api import M5Error, make_payload


def build_context(retrieval, model="deepseek-flash", selected_chunk_ids=None):
    """Keep complete chunks; remove lowest-ranked chunks until both local limits fit.

Both the UTF-8 byte guard and the official offline tokenizer budget are enforced.
"""
    evidence, excluded = [], []
    for result in retrieval["results"]:
        if selected_chunk_ids is not None and result['chunk_id'] not in selected_chunk_ids:
            excluded.append({'chunk_id': result['chunk_id'], 'reason': 'not_in_m4_packed_context'})
            continue
        evidence.append({
            "source_id": f"S{len(evidence) + 1}", "rank": result["rank"],
            "chunk_id": result["chunk_id"], "document_id": result["document_id"],
            "chunk_index": result["chunk_index"], "text": result["text"],
            "text_sha256": result["text_sha256"], "citation": deepcopy(result["citation"]),
        })
    if not evidence:
        raise M5Error('EMPTY_SELECTED_CONTEXT', 'M4 returned candidates but selected no evidence. Check the context budget.')
    while evidence:
        try:
            make_payload(retrieval["query"], evidence, model)
            return evidence, excluded
        except M5Error as exc:
            if exc.code not in {"INPUT_TOO_LARGE", "INPUT_TOKEN_BUDGET_EXCEEDED"}:
                raise
            removed = evidence.pop()
            excluded.append({"chunk_id": removed["chunk_id"], "reason": "input_token_limit" if exc.code == "INPUT_TOKEN_BUDGET_EXCEEDED" else "input_byte_limit"})
    raise M5Error("CONTEXT_TOO_LARGE", "The question or highest-ranked evidence exceeds the input limit. No text was truncated and no API call was made.")
