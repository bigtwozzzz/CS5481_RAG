"""Official offline tokenizer budgeting, with explicit unverified API parity.

Only the system + user, text-only, non-thinking request used by M5 is supported.
The official sample chat template is specialized to those two message roles.
This is not an exact API billing estimator or a general chat-template engine.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from .api import M5Error

ASSET_DIR = Path(__file__).resolve().parents[2] / 'vendor/m5/deepseek_v4_tokenizer'
ASSET_HASHES = {
    'tokenizer.json': '89085f12ef79460ac5f66d1119325ddfc694b4ab209d80bbd81d35f081dc9614',
    'tokenizer_config.json': '841f8cf146e3f0ad1082594a31f68ecf7608c20467ef355081333d85bbaeb1cb',
}
TOKENIZERS_VERSION = '0.22.2'
TOTAL_TOKEN_LIMIT = 8192
SAFETY_MARGIN = 512
SUPPORTED_MODEL = 'deepseek-flash'
PROFILE_SOURCE_URL = 'https://api-docs.deepseek.com/quick_start/token_usage'
BUILTIN_PROFILE_VERSION = 'm5-token-budget-v0.5'
_EXTRA_PROFILES = {}


def builtin_profile():
    return {
        'model': SUPPORTED_MODEL,
        'profile_version': BUILTIN_PROFILE_VERSION,
        'application_total_token_limit': TOTAL_TOKEN_LIMIT,
        'safety_margin_tokens': SAFETY_MARGIN,
        'tokenizer_sha256': ASSET_HASHES['tokenizer.json'],
        'template_sha256': ASSET_HASHES['tokenizer_config.json'],
        'source_url': PROFILE_SOURCE_URL,
    }


def load_budget_profile(path):
    """Register one additional model profile. The built-in deepseek-flash profile stays in place."""
    target = Path(path)
    try:
        text = target.read_text(encoding='utf-8')
    except OSError:
        raise M5Error('BUDGET_PROFILE_UNREADABLE', 'The budget profile file is missing or unreadable.') from None
    if len(text.encode('utf-8')) > 100_000:
        raise M5Error('BUDGET_PROFILE_UNREADABLE', 'The budget profile file is too large.')
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise M5Error('INVALID_BUDGET_PROFILE', 'The budget profile is not valid JSON.') from None
    fields = {'schema_version', 'profile_version', 'model', 'based_on_profile', 'tokenizer_asset_dir',
              'tokenizer_version', 'asset_sha256', 'application_total_token_limit', 'safety_margin_tokens',
              'template_scope', 'source_url', 'provider_tokenizer_parity_verified', 'notes'}
    if not isinstance(data, dict) or set(data) != fields or data.get('schema_version') != 'm5_budget_profile.v1':
        raise M5Error('INVALID_BUDGET_PROFILE', 'Use the documented budget-profile fields.')
    model = data['model']
    if not isinstance(model, str) or not model.strip() or model != model.strip():
        raise M5Error('INVALID_BUDGET_PROFILE', 'The budget profile model name is empty or padded.')
    if model == SUPPORTED_MODEL:
        raise M5Error('BUDGET_PROFILE_CONFLICT', 'The built-in deepseek-flash profile cannot be replaced.')
    if data['based_on_profile'] != BUILTIN_PROFILE_VERSION:
        raise M5Error('INVALID_BUDGET_PROFILE', 'An added profile must name the built-in profile it adapts.')
    if (data['tokenizer_version'] != TOKENIZERS_VERSION or data['provider_tokenizer_parity_verified'] is not False
            or data['template_scope'] != 'official_sample_system_user_add_generation_prompt'
            or not isinstance(data['source_url'], str) or not data['source_url'].startswith('https://')
            or not isinstance(data['profile_version'], str) or not data['profile_version'].strip()
            or not isinstance(data['notes'], str) or not data['notes'].strip()):
        raise M5Error('INVALID_BUDGET_PROFILE', 'Tokenizer version, provenance or parity flag is not acceptable.')
    hashes = data['asset_sha256']
    if not isinstance(hashes, dict) or set(hashes) != set(ASSET_HASHES) or any(hashes[name] != ASSET_HASHES[name] for name in ASSET_HASHES):
        raise M5Error('INVALID_BUDGET_PROFILE', 'An added profile must reuse the pinned tokenizer asset hashes.')
    asset_dir = (Path(__file__).resolve().parents[2] / data['tokenizer_asset_dir']).resolve()
    if asset_dir != ASSET_DIR.resolve():
        raise M5Error('INVALID_BUDGET_PROFILE', 'An added profile must use the existing pinned tokenizer directory.')
    limit, margin = data['application_total_token_limit'], data['safety_margin_tokens']
    if type(limit) is not int or type(margin) is not int or limit <= 0 or margin < 0 or margin >= limit:
        raise M5Error('INVALID_BUDGET_PROFILE', 'Token limit and safety margin must be integers within range.')
    profile = {
        'model': model,
        'profile_version': data['profile_version'],
        'application_total_token_limit': limit,
        'safety_margin_tokens': margin,
        'tokenizer_sha256': hashes['tokenizer.json'],
        'template_sha256': hashes['tokenizer_config.json'],
        'source_url': data['source_url'],
        'path': str(target.resolve()),
    }
    previous = _EXTRA_PROFILES.get(model)
    if previous is not None and previous != profile:
        raise M5Error('BUDGET_PROFILE_CONFLICT', 'This model is already registered with a different budget profile.')
    _EXTRA_PROFILES[model] = profile
    return profile


def profile_for(model):
    if model == SUPPORTED_MODEL:
        return builtin_profile()
    return _EXTRA_PROFILES.get(model)


@lru_cache(maxsize=1)
def load_tokenizer():
    try:
        import tokenizers
    except ImportError:
        raise M5Error('TOKENIZER_NOT_INSTALLED',
                      'Install requirements-m5-tokenizer.txt in this Python environment, then rerun the dry-run.') from None
    if tokenizers.__version__ != TOKENIZERS_VERSION:
        raise M5Error('TOKENIZER_VERSION_MISMATCH', 'This budget profile requires tokenizers==' + TOKENIZERS_VERSION + '.')
    assets = {}
    for name, expected in ASSET_HASHES.items():
        try:
            data = (ASSET_DIR / name).read_bytes()
        except OSError:
            raise M5Error('TOKENIZER_ASSET_MISSING', 'A pinned tokenizer data file is missing or unreadable: ' + name) from None
        if hashlib.sha256(data).hexdigest() != expected:
            raise M5Error('TOKENIZER_ASSET_MISMATCH', 'A tokenizer data file differs from the reviewed version: ' + name)
        assets[name] = data
    try:
        tokenizer = tokenizers.Tokenizer.from_str(assets['tokenizer.json'].decode('utf-8'))
        # Count every token. Never allow hidden truncation or padding in budgeting.
        tokenizer.no_truncation()
        tokenizer.no_padding()
        return tokenizer
    except Exception:
        raise M5Error('TOKENIZER_LOAD_ERROR', 'The pinned tokenizer data could not be loaded. No request was sent.') from None


def render_messages(messages):
    if (not isinstance(messages, list) or len(messages) != 2 or
        any(not isinstance(m, dict) or set(m) != {'role', 'content'} or
            not isinstance(m['content'], str) for m in messages) or
        [m['role'] for m in messages] != ['system', 'user']):
        raise M5Error('UNSUPPORTED_BUDGET_REQUEST', 'Token budgeting supports exactly one system and one text user message.')
    # Equivalent to the official pinned template for the supported request shape.
    return ('<\uff5cbegin\u2581of\u2581sentence\uff5c>' + messages[0]['content'] +
            '<\uff5cUser\uff5c>' + messages[1]['content'] + '<\uff5cAssistant\uff5c>')


def measure_budget(payload):
    profile = profile_for(payload.get('model'))
    if profile is None:
        raise M5Error('UNSUPPORTED_BUDGET_MODEL',
                      'No reviewed tokenizer budget profile for this model. Use deepseek-flash.')
    if (set(payload) != {'model', 'messages', 'response_format', 'thinking', 'temperature', 'max_tokens', 'stream'} or
        payload['thinking'] != {'type': 'disabled'} or
        payload['response_format'] != {'type': 'json_object'} or payload['stream'] is not False):
        raise M5Error('UNSUPPORTED_BUDGET_REQUEST', 'This profile supports text JSON output with thinking and streaming disabled.')
    output_reserve = payload['max_tokens']
    if type(output_reserve) is not int or output_reserve <= 0:
        raise M5Error('INVALID_OUTPUT_RESERVE', 'max_tokens must be a positive integer.')
    rendered = render_messages(payload['messages'])
    try:
        input_tokens = len(load_tokenizer().encode(rendered, add_special_tokens=False).ids)
    except M5Error:
        raise
    except Exception:
        raise M5Error('TOKENIZER_ENCODING_ERROR', 'Cannot count this input with the pinned tokenizer. No request was sent.') from None
    limit = profile['application_total_token_limit']
    margin = profile['safety_margin_tokens']
    required = input_tokens + output_reserve + margin
    return {
        'profile_version': profile['profile_version'],
        'method': 'official_offline_tokenizer',
        'check_status': 'PASS' if required <= limit else 'EXCEEDED',
        'requested_model': payload['model'],
        'tokenizer_version': TOKENIZERS_VERSION,
        'tokenizer_sha256': profile['tokenizer_sha256'],
        'template_sha256': profile['template_sha256'],
        'template_scope': 'official_sample_system_user_add_generation_prompt',
        'source_url': profile['source_url'],
        'includes': ['system_prompt', 'serialized_user_content', 'sample_chat_markers'],
        'input_tokens_local': input_tokens,
        'output_tokens_reserved': output_reserve,
        'safety_margin_tokens': margin,
        'application_total_token_limit': limit,
        'total_tokens_reserved': required,
        'headroom_tokens': limit - required,
        'provider_tokenizer_parity_verified': False,
        'api_usage_is_authoritative': True,
        'payload_sha256': hashlib.sha256(json.dumps(payload, ensure_ascii=False,
            sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest(),
        'provider_input_tokens': None,
        'provider_minus_local_tokens': None,
        'observation': 'not_available',
    }


def check_budget(payload, *, error_code='INPUT_TOKEN_BUDGET_EXCEEDED'):
    report = measure_budget(payload)
    if report['check_status'] != 'PASS':
        raise M5Error(error_code,
                      'Local token budget exceeded: input ' + str(report['input_tokens_local']) +
                      ' + output reserve ' + str(report['output_tokens_reserved']) +
                      ' + safety margin ' + str(report['safety_margin_tokens']) +
                      ' > application limit ' + str(report['application_total_token_limit']) +
                      '. No request was sent for this stage.')
    return report


def observe_usage(report, input_tokens):
    result = deepcopy(report)
    if type(input_tokens) is int and input_tokens >= 0:
        result['provider_input_tokens'] = input_tokens
        result['provider_minus_local_tokens'] = input_tokens - result['input_tokens_local']
        result['observation'] = 'single_response_comparison_not_parity_verification'
    return result


def print_budget(report):
    if report is None:
        return
    print('Local tokenizer budget: ' + report['check_status'] + ' (official offline sample).')
    print('Token budget: input ' + str(report['input_tokens_local']) +
          ' + output reserve ' + str(report['output_tokens_reserved']) +
          ' + safety margin ' + str(report['safety_margin_tokens']) +
          ' <= application limit ' + str(report['application_total_token_limit']) + '.')
    print('Provider tokenizer parity: NOT VERIFIED; API usage is authoritative.')
