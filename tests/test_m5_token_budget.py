"""Offline budget enforcement tests; these do not prove provider tokenizer parity."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.m5_generation.api import M5Error, make_payload
from scripts.m5_generation.generator import generate_answer
from scripts.m5_generation.support import review_answer, make_review_payload, prepare_record
from scripts.m5_generation.pipeline import run_pipeline
from scripts.m5_generation import token_budget as budget

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return json.loads((ROOT/'examples/m5/retrieval_ok.json').read_text(encoding='utf-8'))


def envelope(value):
    return {'model': 'offline-mock', 'choices': [{'finish_reason': 'stop',
            'message': {'content': json.dumps(value) if not isinstance(value, str) else value}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}


def draft():
    return {'status': 'ANSWERED', 'claims': [{'text': 'At least 35 Australians are missing in Nepal.',
            'source_ids': ['S1'], 'evidence_quotes': [{'source_id': 'S1',
            'quote': 'at least 35 Australians missing in Nepal'}]}], 'missing_information': []}


def answer():
    return generate_answer(fixture(), key_provider=lambda: 'fake', api_call=Mock(return_value=envelope(draft())))


class TokenBudgetTests(unittest.TestCase):
    def test_actual_official_tokenizer_and_asset_hash(self):
        data = (budget.ASSET_DIR/'tokenizer.json').read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), budget.ASSET_HASHES['tokenizer.json'])
        # Published demo input, encoded by the actual installed tokenizer, not a mock.
        tok = budget.load_tokenizer()
        self.assertEqual(tok.decode(tok.encode('Hello!', add_special_tokens=False).ids), 'Hello!')
        self.assertIsNone(tok.truncation)
        self.assertIsNone(tok.padding)

    def test_all_serialized_fields_and_chat_markers_counted(self):
        payload = make_payload('Question?', [{'text': 'Evidence', 'citation': {'title': 'Title'}}], 'deepseek-flash')
        report = budget.check_budget(payload)
        rendered = budget.render_messages(payload['messages'])
        self.assertIn('Title', rendered)
        self.assertEqual(report['input_tokens_local'], len(budget.load_tokenizer().encode(rendered, add_special_tokens=False).ids))
        self.assertEqual(report['output_tokens_reserved'], payload['max_tokens'])
        self.assertFalse(report['provider_tokenizer_parity_verified'])

    def test_exact_boundary_passes_then_one_token_over_fails(self):
        payload = make_payload('Q', [], 'deepseek-flash')
        required = budget.measure_budget(payload)['total_tokens_reserved']
        with patch.object(budget, 'TOTAL_TOKEN_LIMIT', required):
            self.assertEqual(budget.check_budget(payload)['headroom_tokens'], 0)
            payload['max_tokens'] += 1
            with self.assertRaises(M5Error) as caught:
                budget.check_budget(payload)
            self.assertEqual(caught.exception.code, 'INPUT_TOKEN_BUDGET_EXCEEDED')

    def test_multilingual_text_is_counted_without_character_ratio(self):
        text = 'English 123 \u4e2d\u6587 \U0001f680 e\u0301'
        payload = make_payload(text, [], 'deepseek-flash')
        self.assertEqual(json.loads(payload['messages'][1]['content'])['QUESTION'], text)
        self.assertEqual(budget.check_budget(payload)['check_status'], 'PASS')

    def test_m4_selected_evidence_retained_and_immutable(self):
        data = json.loads((ROOT/'documents/m4/m5_hybrid_C_example.json').read_text(encoding='utf-8'))
        original = deepcopy(data)
        r = run_pipeline(data, dry_run=True)
        self.assertEqual(r['status'], 'READY_FOR_PIPELINE')
        self.assertEqual(len(r['preview']['evidence']), 3)
        self.assertEqual(r['evidence_chunk_ids'], data['selected_chunk_ids'])
        self.assertEqual(r['preview']['token_budget']['input_tokens_local'], 2217)  # v0.7.2 prompt with unchanged M4 evidence
        self.assertEqual(data, original)
        self.assertEqual(r['api_calls'], [])

    def test_token_dense_low_rank_chunk_removed_whole(self):
        data = fixture()
        data['results'][1]['text'] = '1!' * 4000
        data['results'][1]['text_sha256'] = hashlib.sha256(data['results'][1]['text'].encode()).hexdigest()
        r = generate_answer(data, dry_run=True)
        self.assertEqual(r['status'], 'READY_FOR_GENERATION')
        self.assertEqual(len(r['evidence']), 1)
        self.assertEqual(r['evidence'][0]['text'], data['results'][0]['text'])
        self.assertEqual(r['excluded_evidence'][0]['reason'], 'input_token_limit')

    def test_unfit_top_chunk_stops_before_key_or_api(self):
        data = fixture()
        data['results'][0]['text'] = '1!' * 4000
        data['results'][0]['text_sha256'] = hashlib.sha256(data['results'][0]['text'].encode()).hexdigest()
        api, key = Mock(), Mock()
        r = generate_answer(data, api_call=api, key_provider=key)
        self.assertEqual(r['error']['code'], 'CONTEXT_TOO_LARGE')
        api.assert_not_called(); key.assert_not_called()

    def test_semantic_feedback_cannot_shrink_or_bypass_budget(self):
        data = fixture()
        original = deepcopy(data)
        api, key = Mock(), Mock()
        r = generate_answer(data, revision_feedback={'reason': '1!' * 3500}, api_call=api, key_provider=key)
        self.assertEqual(r['error']['code'], 'REPAIR_TOKEN_BUDGET_EXCEEDED')
        self.assertEqual(len(r['evidence']), 2)
        self.assertEqual(data, original)
        api.assert_not_called(); key.assert_not_called()

    def test_appended_format_repair_instruction_rechecked(self):
        preview = generate_answer(fixture(), dry_run=True)
        limit = preview['token_budget']['total_tokens_reserved']
        api = Mock(return_value=envelope('not JSON'))
        with patch.object(budget, 'TOTAL_TOKEN_LIMIT', limit):
            r = generate_answer(fixture(), repair_once=True, api_call=api, key_provider=lambda: 'fake')
        self.assertEqual(r['error']['code'], 'REPAIR_TOKEN_BUDGET_EXCEEDED')
        self.assertEqual(api.call_count, 1)

    def test_review_counts_draft_and_reserves_review_output(self):
        original = answer()
        r = review_answer(original, dry_run=True)
        payload = make_review_payload(prepare_record(original), 'deepseek-flash')
        self.assertEqual(r['decision'], 'READY_FOR_REVIEW')
        self.assertEqual(r['token_budget']['payload_sha256'], budget.measure_budget(payload)['payload_sha256'])
        self.assertEqual(r['token_budget']['output_tokens_reserved'], 2400)
        self.assertIn('DRAFT', payload['messages'][1]['content'])

    def test_review_overflow_keeps_evidence_and_uses_zero_calls(self):
        source = answer()
        source['query'] = '1!' * 3500
        original = deepcopy(source)
        api, key = Mock(), Mock()
        r = review_answer(source, api_call=api, key_provider=key)
        self.assertEqual(r['error']['code'], 'REVIEW_TOKEN_BUDGET_EXCEEDED')
        self.assertEqual(r['judge']['calls'], 0)
        self.assertEqual(source, original)
        api.assert_not_called(); key.assert_not_called()

    def test_unknown_model_fails_before_key(self):
        api, key = Mock(), Mock()
        r = run_pipeline(fixture(), model='unknown-model', api_call=api, key_provider=key)
        self.assertEqual(r['error']['code'], 'UNSUPPORTED_BUDGET_MODEL')
        api.assert_not_called(); key.assert_not_called()

    def test_missing_dependency_does_not_fall_back_to_bytes(self):
        budget.load_tokenizer.cache_clear()
        try:
            with patch.dict(sys.modules, {'tokenizers': None}):
                api, key = Mock(), Mock()
                r = run_pipeline(fixture(), api_call=api, key_provider=key)
            self.assertEqual(r['error']['code'], 'TOKENIZER_NOT_INSTALLED')
            api.assert_not_called(); key.assert_not_called()
        finally:
            budget.load_tokenizer.cache_clear()

    def test_tampered_tokenizer_is_refused(self):
        budget.load_tokenizer.cache_clear()
        try:
            with tempfile.TemporaryDirectory() as temp:
                (Path(temp)/'tokenizer.json').write_text('{}', encoding='utf-8')
                with patch.object(budget, 'ASSET_DIR', Path(temp)):
                    with self.assertRaises(M5Error) as caught:
                        budget.load_tokenizer()
                    self.assertEqual(caught.exception.code, 'TOKENIZER_ASSET_MISMATCH')
        finally:
            budget.load_tokenizer.cache_clear()

    def test_unsupported_shapes_and_thinking_are_refused(self):
        payload = make_payload('Q', [], 'deepseek-flash')
        for changes in [{'thinking': {'type': 'enabled'}}, {'tools': []}, {'max_tokens': True},
                        {'messages': [{'role': 'user', 'content': 'Q'}]}]:
            with self.assertRaises(M5Error):
                budget.measure_budget({**payload, **changes})

    def test_usage_delta_recorded_without_claiming_parity(self):
        report = budget.check_budget(make_payload('Q', [], 'deepseek-flash'))
        self.assertIsNone(budget.observe_usage(report, None)['provider_minus_local_tokens'])
        self.assertIsNone(budget.observe_usage(report, True)['provider_minus_local_tokens'])
        observed = budget.observe_usage(report, report['input_tokens_local'] + 24)
        self.assertEqual(observed['provider_minus_local_tokens'], 24)
        self.assertFalse(observed['provider_tokenizer_parity_verified'])
        self.assertIsNone(report['provider_input_tokens'])

    def test_per_call_budget_tracks_actual_payload_without_key(self):
        api = Mock(side_effect=[envelope('bad JSON'), envelope(draft())])
        r = generate_answer(fixture(), repair_once=True, api_call=api, key_provider=lambda: 'fake-secret')
        self.assertEqual(r['status'], 'ANSWERED')
        calls = r['generation']['calls']
        self.assertGreater(calls[1]['token_budget']['input_tokens_local'], calls[0]['token_budget']['input_tokens_local'])
        for call, actual in zip(calls, api.call_args_list):
            self.assertEqual(call['token_budget']['payload_sha256'], budget.check_budget(actual.args[0])['payload_sha256'])
            self.assertEqual(call['token_budget']['provider_input_tokens'], 100)
        self.assertNotIn('fake-secret', json.dumps(r))


if __name__ == '__main__':
    unittest.main()
