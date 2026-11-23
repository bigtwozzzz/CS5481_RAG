from .api import M5Error
import re


def require_english_prose(values):
    """Reject CJK prose; this guard is not a full natural-language classifier.

    Exact quotes, metadata and historical input are exempt from translation.
    The prompt specifies English for other languages as well.
    """
    if any(re.search(r'[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]', text) for text in values):
        raise M5Error('OUTPUT_LANGUAGE_MISMATCH', 'Generated prose must be in English. Exact source quotes remain unchanged.')

def validate_citations(claim, evidence):
    """Locate citations for one claim; do not infer semantic support."""
    errors = []
    located_quotes = []
    source_map = {item["source_id"]: item for item in evidence}

    def finish():
        return {
            "citation_checks": "fail" if errors else "pass",
            "support": "unchecked",
            "errors": errors,
            "located_quotes": located_quotes,
        }

    if not isinstance(claim, dict):
        errors.append("Each claim must be an object")
        return finish()
    if not isinstance(claim.get("text"), str) or not claim["text"].strip():
        errors.append("Claim text must be nonempty")

    source_ids = claim.get("source_ids")
    if (not isinstance(source_ids, list) or not source_ids
            or not all(isinstance(sid, str) and sid for sid in source_ids)):
        errors.append("Each claim requires a nonempty source_ids list")
        return finish()
    if len(source_ids) != len(set(source_ids)):
        errors.append("Source IDs must be unique")
    for sid in source_ids:
        if sid not in source_map:
            errors.append(f"Unknown source ID: {sid}")

    quotes = claim.get("evidence_quotes")
    if not isinstance(quotes, list) or not quotes:
        errors.append("Each claim requires exact evidence quotes")
        return finish()

    matched_sources = set()
    for item in quotes:
        if not isinstance(item, dict):
            errors.append("Each quote must be an object")
            continue
        sid = item.get("source_id")
        quote = item.get("quote")
        if not isinstance(sid, str) or sid not in source_map:
            errors.append(f"Quote uses an unknown source: {sid}")
            continue
        if sid not in source_ids:
            errors.append(f"Quote source is absent from source_ids: {sid}")
            continue
        if not isinstance(quote, str) or not quote.strip():
            errors.append(f"{sid} requires a nonempty quote")
            continue

        # Exact match: preserve whitespace, case and punctuation.
        # When the quote occurs repeatedly, record its first occurrence.
        start = source_map[sid]["text"].find(quote)
        if start == -1:
            errors.append(f"Quote not found in the text for {sid}")
            continue
        matched_sources.add(sid)
        located_quotes.append({
            "source_id": sid,
            "chunk_id": source_map[sid]["chunk_id"],
            "quote": quote,
            "char_start": start,
            "char_end": start + len(quote),
        })

    for sid in sorted(set(source_ids) - matched_sources):
        errors.append(f"No matching quote for source {sid}")
    return finish()

def validate_draft(draft, evidence, *, enforce_english=False):
    def schema_error():
        raise M5Error("INVALID_ANSWER_SCHEMA", "Invalid model output fields or status. No answer is displayed.")

    if not isinstance(draft, dict) or set(draft) != {"status", "claims", "missing_information"}:
        schema_error()
    status, claims, missing = draft["status"], draft["claims"], draft["missing_information"]
    if not isinstance(status, str) or status not in {"ANSWERED", "PARTIAL", "INSUFFICIENT_SOURCES"}:
        schema_error()
    if not isinstance(claims, list) or not isinstance(missing, list):
        schema_error()
    if not all(isinstance(item, str) and item.strip() for item in missing):
        schema_error()
    if status == "ANSWERED" and (not claims or missing):
        schema_error()
    if status == "PARTIAL" and (not claims or not missing):
        schema_error()
    if status == "INSUFFICIENT_SOURCES" and (claims or not missing):
        schema_error()
    checked = []
    for index, claim in enumerate(claims, 1):
        if not isinstance(claim, dict) or set(claim) != {"text", "source_ids", "evidence_quotes"}:
            schema_error()
        if not isinstance(claim["evidence_quotes"], list):
            schema_error()
        for quote in claim["evidence_quotes"]:
            if not isinstance(quote, dict) or set(quote) != {"source_id", "quote"}:
                schema_error()
        validation = validate_citations(claim, evidence)
        if validation["citation_checks"] != "pass":
            raise M5Error("CITATION_VALIDATION_FAILED", f"Claim {index} failed source or exact-quote validation. The entire draft was blocked.")
        checked.append({**claim, "claim_id": f"C{index}", "located_quotes": validation["located_quotes"]})
    used = {sid for claim in checked for sid in claim["source_ids"]}
    if enforce_english:
        require_english_prose([claim['text'] for claim in checked] + missing)
    return {
        "review_required": True,
        "model_proposed_status": status,
        "claims": checked,
        "sources": [source for source in evidence if source["source_id"] in used],
        "missing_information": missing,
        "validation": {"schema": "pass", "citations": "pass" if checked else "not_applicable", "support": "unchecked" if checked else "not_applicable"},
    }
