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
    if payload.get('model') != SUPPORTED_MODEL:
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
    required = input_tokens + output_reserve + SAFETY_MARGIN
    return {
        'profile_version': 'm5-token-budget-v0.5',
        'method': 'official_offline_tokenizer',
        'check_status': 'PASS' if required <= TOTAL_TOKEN_LIMIT else 'EXCEEDED',
        'requested_model': payload['model'],
        'tokenizer_version': TOKENIZERS_VERSION,
        'tokenizer_sha256': ASSET_HASHES['tokenizer.json'],
        'template_sha256': ASSET_HASHES['tokenizer_config.json'],
        'template_scope': 'official_sample_system_user_add_generation_prompt',
        'source_url': 'https://api-docs.deepseek.com/quick_start/token_usage',
        'includes': ['system_prompt', 'serialized_user_content', 'sample_chat_markers'],
        'input_tokens_local': input_tokens,
        'output_tokens_reserved': output_reserve,
        'safety_margin_tokens': SAFETY_MARGIN,
        'application_total_token_limit': TOTAL_TOKEN_LIMIT,
        'total_tokens_reserved': required,
        'headroom_tokens': TOTAL_TOKEN_LIMIT - required,
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
