"""Runtime checks for the proposed retrieval_response.v1 boundary.

These validate structure and internal consistency, not authenticity of source metadata.
"""
import hashlib
import math
import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from .api import M5Error


def require(condition, field):
    if not condition:
        raise M5Error("INVALID_RETRIEVAL", "Invalid retrieval response: " + field)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def sha256(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def valid_utc(value):
    if not isinstance(value, str) or "T" not in value:
        return False
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return date.tzinfo is not None and date.utcoffset() == timedelta(0)
    except ValueError:
        return False


def validate_retrieval(data):
    require(isinstance(data, dict), "Root must be an object")
    if data.get('schema_version') == 'retrieval_response.v2':
        from .m4_input import validate_v2
        return validate_v2(data)
    required = {"schema_version", "request_id", "query", "retrieval_query", "status", "index",
                "config", "filters", "results", "timing_ms", "warnings", "error"}
    require(required <= set(data), "Missing required top-level fields")
    require(data["schema_version"] == "retrieval_response.v1", "schema_version")
    require(nonempty(data["request_id"]), "request_id")
    require(nonempty(data["query"]), "query must not be blank")
    require(nonempty(data["retrieval_query"]), "retrieval_query must not be blank")
    status = data["status"]
    require(isinstance(status, str) and status in {"OK", "NO_EVIDENCE", "ERROR"}, "status")
    results = data["results"]
    require(isinstance(results, list), "results")
    require(isinstance(data["warnings"], list) and all(nonempty(w) for w in data["warnings"]), "warnings")
    require(data["filters"] is None or isinstance(data["filters"], dict), "filters")
    timing = data["timing_ms"]
    require(isinstance(timing, dict) and {"encode", "search", "rerank", "total"} <= set(timing), "timing_ms")
    require(all(number(v) and v >= 0 for v in timing.values()), "timing_ms must contain finite nonnegative numbers")
    if status == "ERROR":
        error = data["error"]
        require(isinstance(error, dict) and nonempty(error.get("code")) and nonempty(error.get("message")), "error.code/message")
        require(not results, "ERROR requires results=[]")
    else:
        require(data["error"] is None, "error must be null unless status is ERROR")
        require(bool(results) if status == "OK" else not results, "status is inconsistent with results")

    index = data["index"]
    if not (status == "ERROR" and index is None):
        require(isinstance(index, dict), "index")
        require(isinstance(index.get("strategy"), str) and index["strategy"] in {"A", "B", "C"}, "index.strategy")
        require(nonempty(index.get("collection")) and sha256(index.get("manifest_sha256")), "index.collection/manifest_sha256")
    config = data["config"]
    require(isinstance(config, dict) and nonempty(config.get("mode")), "config.mode")
    for field in ("candidate_k", "top_k"):
        require(type(config.get(field)) is int and config[field] > 0, "config." + field)
    require(config["candidate_k"] >= config["top_k"], "candidate_k >= top_k")
    require(len(results) <= config["top_k"], "results exceeds top_k")

    seen = set()
    for rank, result in enumerate(results, 1):
        require(isinstance(result, dict), f"results[{rank}]")
        require(type(result.get("rank")) is int and result["rank"] == rank, "rank must be consecutive starting at 1")
        cid = result.get("chunk_id")
        require(sha256(cid), "chunk_id must be a SHA-256 string")
        require(cid not in seen, "Duplicate chunk_id")
        seen.add(cid)
        require(nonempty(result.get("document_id")), "document_id")
        require(type(result.get("chunk_index")) is int and result["chunk_index"] >= 0, "chunk_index")
        text = result.get("text")
        require(nonempty(text), "text")
        require(result.get("text_sha256") == hashlib.sha256(text.encode("utf-8")).hexdigest(), "text_sha256 does not match the evidence text")
        methods = result.get("retrieved_by")
        require(isinstance(methods, list) and methods and all(nonempty(m) for m in methods), "retrieved_by")
        scores = result.get("scores")
        require(isinstance(scores, dict) and {"distance", "similarity", "bm25", "rrf", "rerank"} <= set(scores), "scores")
        require(all(v is None or number(v) for v in scores.values()), "scores must be finite numbers or null")
        distance, similarity = scores["distance"], scores["similarity"]
        require("dense" in methods or (distance is None and similarity is None), "Non-dense evidence must not contain cosine scores")
        if similarity is not None:
            require(distance is not None and math.isclose(similarity, 1 - distance, abs_tol=1e-6), "similarity must equal 1-distance")
        citation = result.get("citation")
        require(isinstance(citation, dict), "citation")
        for field in ("url", "title", "published_at_utc", "source_name", "source_domain"):
            require(nonempty(citation.get(field)), "citation." + field)
        require(valid_utc(citation["published_at_utc"]), "published_at_utc must use UTC")
        try:
            url = urlsplit(citation["url"])
            domain = citation["source_domain"].lower()
            valid_url = (not any(c.isspace() for c in citation["url"])
                         and url.scheme in ("http", "https") and bool(url.hostname)
                         and not url.username and not url.password
                         and (url.hostname == domain or url.hostname.endswith("." + domain)))
        except ValueError:
            valid_url = False
        require(valid_url, "Source URL does not match source_domain")
    return data
