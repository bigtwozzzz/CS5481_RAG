"""File/API integration baseline. Outputs remain drafts until semantic review."""
import time
from copy import deepcopy
from datetime import datetime, timezone
from .api import M5Error, PROMPT_VERSION, call_api, make_payload, parse_envelope, read_key
from .context import build_context
from .render import render_body
from .contracts import nonempty, validate_retrieval
from .validator import validate_draft
from .m4_input import prepare_input
from .token_budget import check_budget, observe_usage


def generate_answer(retrieval, *, dry_run=False, model="deepseek-flash", repair_once=False,
                    key_provider=read_key, api_call=call_api, revision_feedback=None):
    started = time.perf_counter()
    result = {
        "schema_version": "answer_response.v1", "implementation_version": "m5-token-budget-v0.5",
        "output_language": "en",
        "request_id": retrieval.get("request_id") if isinstance(retrieval, dict) and nonempty(retrieval.get("request_id")) else None,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "ERROR", "claims": [], "sources": [], "answer": "", "missing_information": [],
        "review_required": False, "publication_ready": False,
        "validation": {"input": "unchecked", "schema": "unchecked", "citation_ids": "not_applicable",
                       "quote_match": "not_applicable", "support": "not_applicable", "answerability": "unchecked"},
        "generation": {"model": model, "prompt_version": PROMPT_VERSION, "calls": [],
                       "max_calls": 2 if repair_once else 1, "input_tokens": 0, "output_tokens": 0,
                       "token_usage_complete": True, "latency_ms": 0, "cost_usd": None},
        "evidence": [], "excluded_evidence": [], "warnings": [], "validation_log": [], "error": None,
    }
    try:
        retrieval, input_meta = prepare_input(retrieval)
        result['request_id'] = retrieval['request_id']
        result['m4_input'] = input_meta
        result["validation"]["input"] = "pass"
        result["index"] = deepcopy(retrieval["index"])
        result["query"] = retrieval["query"]
        result["retrieval_query"] = retrieval["retrieval_query"]
        result["retrieval_config"] = deepcopy(retrieval["config"])
        result["filters"] = deepcopy(retrieval["filters"])
        result["retrieval_timing_ms"] = deepcopy(retrieval["timing_ms"])
        result["warnings"] = list(retrieval["warnings"])
        if retrieval.get("fixture"):
            result["fixture"] = deepcopy(retrieval["fixture"])
        if retrieval["status"] == "ERROR":
            result["upstream_error"] = deepcopy(retrieval["error"])
            raise M5Error("RETRIEVAL_ERROR", "Retrieval failed. An answer cannot be generated.")
        if retrieval["status"] == "NO_EVIDENCE":
            result.update(status="INSUFFICIENT_SOURCES", publication_ready=False, review_required=True,
                          answer="The current retrieval returned no evidence to support an answer.",
                          missing_information=["Retrieved evidence supporting an answer to the question"])
            result["validation"].update(schema="pass", answerability="no_retrieval_evidence")
            return result

        evidence, excluded = build_context(retrieval, model, input_meta['selected_chunk_ids'])
        result["evidence"], result["excluded_evidence"] = evidence, excluded
        input_meta['final_evidence_chunk_ids'] = [item['chunk_id'] for item in evidence]
        if any(item['reason'] in {'input_byte_limit', 'input_token_limit'} for item in excluded):
            result["warnings"].append("Lower-ranked evidence was excluded by the input size limit; assess the coverage impact.")
        result["context_limit"] = {"method": "utf8_bytes", "limit": 16000,
                                    "includes": "system_prompt_and_serialized_user_content",
                                    "model_tokenizer_budget_implemented": True, "provider_tokenizer_parity_verified": False}
        payload = make_payload(retrieval["query"], evidence, model, revision_feedback=revision_feedback)
        result["token_budget"] = check_budget(payload)
        if revision_feedback is not None:
            result['revision_feedback'] = deepcopy(revision_feedback)
        if dry_run:
            result.update(schema_version="m5_evidence_preview.v1", status="READY_FOR_GENERATION")
            result["validation"]["schema"] = "not_applicable"
            return result

        key = key_provider()
        try:
            checked = None
            for attempt in range(result["generation"]["max_calls"]):
                call_log = {"attempt": attempt + 1, "input_tokens": None, "output_tokens": None,
                            "returned_model": None, "latency_ms": None, "error_code": None,
                            "token_budget": check_budget(payload)}
                result["generation"]["calls"].append(call_log)
                api_start = time.perf_counter()
                try:
                    envelope = api_call(payload, key)
                except M5Error as exc:
                    call_log["error_code"] = exc.code
                    raise
                finally:
                    call_log["latency_ms"] = round((time.perf_counter() - api_start) * 1000, 2)
                if isinstance(envelope, dict):
                    call_log["returned_model"] = envelope.get("model")
                    usage = envelope.get("usage")
                    if isinstance(usage, dict):
                        for local, remote in (("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens")):
                            value = usage.get(remote)
                            if type(value) is int and value >= 0:
                                call_log[local] = value
                call_log["token_budget"] = observe_usage(call_log["token_budget"], call_log["input_tokens"])
                try:
                    draft = parse_envelope(envelope)
                    checked = validate_draft(draft, evidence, enforce_english=True)
                    result["validation_log"].append({"attempt": attempt + 1, "result": "pass"})
                    break
                except M5Error as exc:
                    result["validation_log"].append({"attempt": attempt + 1, "result": "fail", "code": exc.code})
                    repairable = exc.code in {"INVALID_JSON", "EMPTY_MODEL_OUTPUT", "INCOMPLETE_RESPONSE",
                                             "INVALID_ANSWER_SCHEMA", "CITATION_VALIDATION_FAILED", "OUTPUT_LANGUAGE_MISMATCH"}
                    if attempt + 1 == result["generation"]["max_calls"] or not repairable:
                        raise
                    # Keep precisely the same evidence. Do not fetch external sources.
                    # Regenerate once without echoing unsafe rejected model content.
                    payload = make_payload(retrieval["query"], evidence, model, revision_feedback=revision_feedback)
                    payload["messages"][0]["content"] += (
                        "\nThe previous output failed validation (" + exc.code + "). Regenerate once using the same evidence, "
                        "following the schema, exact-quote rules and source whitelist.")
                    full_text = ''.join(message["content"] for message in payload["messages"])
                    if len(full_text.encode("utf-8")) > 16000:
                        raise M5Error("REPAIR_INPUT_TOO_LARGE", "The repair prompt exceeds the input limit. No second request was sent.")
                    check_budget(payload, error_code="REPAIR_TOKEN_BUDGET_EXCEEDED")
        finally:
            key = None

        result.update(status=checked["model_proposed_status"], claims=checked["claims"],
                      sources=deepcopy(checked["sources"]), missing_information=checked["missing_information"],
                      review_required=True, publication_ready=False)
        # Metadata is copied from M4, never generated by the LLM.
        for source in result["sources"]:
            for field in ("url", "title", "published_at_utc"):
                source[field] = source["citation"][field]
        has_claims = bool(result["claims"])
        result["validation"].update(schema="pass", citation_ids="pass" if has_claims else "not_applicable",
                                    quote_match="pass" if has_claims else "not_applicable",
                                    support="unchecked" if has_claims else "not_applicable",
                                    answerability="unchecked")
        result["answer"] = render_body(result['claims'], result['missing_information'])
    except M5Error as exc:
        result.update(status="ERROR", claims=[], sources=[], answer="", review_required=False,
                      publication_ready=False, error={"code": exc.code, "message": str(exc)})
        if exc.diagnostics is not None:
            result['error']['diagnostics'] = deepcopy(exc.diagnostics)
        if exc.code == "INVALID_RETRIEVAL":
            result["validation"]["input"] = "fail"
    finally:
        calls = result["generation"]["calls"]
        for field in ("input_tokens", "output_tokens"):
            if all(call[field] is not None for call in calls):
                result["generation"][field] = sum(call[field] for call in calls)
            else:
                result["generation"][field] = None
                result["generation"]["token_usage_complete"] = False
        result["generation"]["latency_ms"] = round(sum(call["latency_ms"] or 0 for call in calls), 2)
        result["timing_ms"] = {"total": round((time.perf_counter() - started) * 1000, 2)}
    return result
