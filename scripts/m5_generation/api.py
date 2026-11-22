import os
import hashlib
import json
import math
import socket
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "https://api.deepseek.com/chat/completions"
PROMPT_VERSION = "m5-generation-en-v0.7.2"
SYSTEM_PROMPT = (Path(__file__).parent / "prompts/generation_v1.txt").read_text(encoding="utf-8")
class M5Error(Exception):
    def __init__(self, code, message, diagnostics=None):
        super().__init__(message)
        self.code = code
        self.diagnostics = diagnostics

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise M5Error("UNEXPECTED_REDIRECT", "The API returned a redirect. The request was stopped.")

def strict_json(text, *, source='json_text'):
    class InvalidNumber(ValueError):
        pass

    class DuplicateKey(ValueError):
        pass

    def reject_constant(value):
        raise InvalidNumber("Non-finite JSON number")

    def reject_duplicate(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise DuplicateKey("Duplicate JSON field")
            result[key] = value
        return result

    def finite_float(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise InvalidNumber("Non-finite JSON float")
        return parsed

    try:
        return json.loads(text, parse_constant=reject_constant, parse_float=finite_float,
                          object_pairs_hook=reject_duplicate)
    except (ValueError, TypeError, RecursionError) as exc:
        details = {'source':source, 'diagnostics_version':'m5-json-diagnostics-v0.4.1'}
        if isinstance(exc, json.JSONDecodeError):
            details.update(reason='syntax_error', description=exc.msg,
                           line=exc.lineno, column=exc.colno, position=exc.pos)
        elif isinstance(exc, DuplicateKey):
            details.update(reason='duplicate_key', description='Duplicate object keys are rejected.')
        elif isinstance(exc, InvalidNumber):
            details.update(reason='nonfinite_number', description='Non-finite numbers are rejected.')
        elif isinstance(exc, RecursionError):
            details.update(reason='nesting_limit', description='JSON nesting exceeds the parser limit.')
        elif isinstance(exc, TypeError):
            details.update(reason='invalid_input_type', description='Expected JSON text.')
        else:
            details.update(reason='parse_error', description='JSON parsing failed under the runtime limits.')
        if isinstance(text, str):
            details['character_count'] = len(text)
            details['text_sha256'] = hashlib.sha256(text.encode('utf-8', errors='surrogatepass')).hexdigest()
            if source == 'model_content':
                # Diagnostic data only. Never display or execute it as an accepted answer.
                details['model_text_excerpt'] = text[:16384]
                details['excerpt_truncated'] = len(text) > 16384
        raise M5Error('INVALID_JSON', 'Invalid JSON (' + details['reason'] + '); no answer is displayed.', details) from None

def make_payload(question, evidence, model, revision_feedback=None, system_prompt=None):
    data = {"QUESTION": question, "EVIDENCE": evidence}
    if revision_feedback is not None:
        data['REVISION_FEEDBACK'] = revision_feedback
    system = SYSTEM_PROMPT if system_prompt is None else system_prompt
    if revision_feedback is not None:
        system += '\n' + (Path(__file__).parent / 'prompts/repair_v1.txt').read_text(encoding='utf-8')
    user_content = json.dumps(data, ensure_ascii=False, allow_nan=False)
    # Temporary byte guard, not a model tokenizer budget.
    if len((system + user_content).encode("utf-8")) > 16000:
        code = 'REPAIR_INPUT_TOO_LARGE' if revision_feedback is not None else 'INPUT_TOO_LARGE'
        raise M5Error(code, "Input exceeds the temporary 16 KB text limit. No request was sent.")
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user_content}],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "temperature": 0.1,
        "max_tokens": 1600,
        "stream": False,
    }

    from .token_budget import check_budget
    check_budget(payload, error_code='REPAIR_TOKEN_BUDGET_EXCEEDED' if revision_feedback is not None
                 else 'INPUT_TOKEN_BUDGET_EXCEEDED')
    return payload

def configured_endpoint():
    base = os.environ.get('M5_API_BASE')
    if not base:
        if os.environ.get('M5_API_KEY'):
            raise M5Error('MISSING_API_BASE', 'M5_API_KEY requires its corresponding M5_API_BASE.')
        return ENDPOINT
    from urllib.parse import urlsplit
    parsed = urlsplit(base)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment):
        raise M5Error('INVALID_API_BASE', 'M5_API_BASE must be an HTTPS base URL without credentials, query or fragment.')
    return base.rstrip('/') + '/chat/completions'


def call_api(payload, key):
    request = urllib.request.Request(
        configured_endpoint(), data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=45) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise M5Error("RESPONSE_TOO_LARGE", "API response exceeds the size limit. Parsing stopped.")
        return strict_json(raw.decode("utf-8"), source='api_response_body')
    except urllib.error.HTTPError as exc:
        messages = {
            400: "Request rejected. Check the model name and parameters.",
            401: "Authentication failed. Check the key for the configured API service.",
            402: "Insufficient API credit. Check the configured API service balance.",
            403: "Account access denied. Check platform permissions.",
            404: "Endpoint or model unavailable. Check the official model name.",
            422: "Invalid request parameters. Check the model and input.",
            429: "Rate limited. Try again later.",
        }
        code = exc.code
        exc.close()
        raise M5Error(f"HTTP_{code}", messages.get(code, "The API service returned an error. Try again later.")) from None
    except (TimeoutError, socket.timeout):
        raise M5Error("API_TIMEOUT", "API request timed out; the provider outcome may be unknown.") from None
    except urllib.error.URLError:
        raise M5Error("NETWORK_ERROR", "Cannot connect to DeepSeek. Check your network or proxy settings.") from None
    except UnicodeError:
        raise M5Error("INVALID_API_RESPONSE", "Cannot decode the API response.") from None

def parse_envelope(envelope):
    try:
        choice = envelope["choices"][0]
        finish_reason = choice["finish_reason"]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise M5Error("INVALID_API_RESPONSE", "Unexpected API response structure.") from None
    if finish_reason != "stop":
        raise M5Error("INCOMPLETE_RESPONSE", "Model output did not finish normally; the output limit may have been reached.")
    if not isinstance(content, str) or not content.strip():
        raise M5Error("EMPTY_MODEL_OUTPUT", "The model returned empty content. No automatic retry was made.")
    try:
        return strict_json(content, source='model_content')
    except M5Error as exc:
        if exc.diagnostics is not None:
            exc.diagnostics['finish_reason'] = finish_reason
        raise

def read_key():
    """Read one process environment variable; never prompt, echo or persist it."""
    configured_endpoint()  # Never send a gateway key to the default provider.
    key = os.environ.get('M5_API_KEY') if os.environ.get('M5_API_BASE') else os.environ.get('DEEPSEEK_API_KEY')
    if key is None or not key.strip():
        raise M5Error('MISSING_API_KEY', 'Set M5_API_KEY for M5_API_BASE, or DEEPSEEK_API_KEY for the default provider.')
    if key != key.strip() or any(c.isspace() for c in key) or not key.isascii():
        raise M5Error('INVALID_API_KEY', 'The API key must contain one nonempty ASCII value without whitespace.')
    return key
