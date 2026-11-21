"""Offline boundary tests, not measurements of model quality."""
import copy
import json
import re
import unittest
from pathlib import Path
from unittest.mock import Mock
from scripts.m5_generation.generator import generate_answer
from scripts.m5_generation.support import review_answer

ROOT = Path(__file__).resolve().parents[1]


def sample():
    return json.loads((ROOT/'documents/m4/m5_hybrid_C_example.json').read_text(encoding='utf-8'))


def response(draft):
    return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(draft)}}]}


def draft():
    return {'status': 'ANSWERED', 'claims': [{'text': 'An offline test claim.',
            'source_ids': ['S1'], 'evidence_quotes': [{'source_id': 'S1',
            'quote': sample()['retrieval']['results'][0]['text'][:80]}]}], 'missing_information': []}


class V2EnglishTests(unittest.TestCase):
    def blocked(self, value, code='INVALID_RETRIEVAL'):
        api, key = Mock(), Mock()
        result = generate_answer(value, api_call=api, key_provider=key)
        self.assertEqual(result['status'], 'ERROR')
        self.assertEqual(result['error']['code'], code)
        api.assert_not_called()
        key.assert_not_called()

    def test_saved_example_selects_three_of_five_without_mutating_input(self):
        value = sample()
        original = copy.deepcopy(value)
        api, key = Mock(), Mock()
        result = generate_answer(value, dry_run=True, api_call=api, key_provider=key)
        self.assertEqual(result['status'], 'READY_FOR_GENERATION')
        self.assertEqual([e['chunk_id'] for e in result['evidence']], value['selected_chunk_ids'])
        self.assertEqual(len(result['evidence']), 3)
        self.assertEqual(len(result['excluded_evidence']), 2)
        self.assertEqual(result['m4_input']['original_input'], value)
        self.assertEqual(value, original)
        self.assertFalse(result['m4_input']['generation_token_budget_verified'])
        api.assert_not_called()
        key.assert_not_called()

    def test_only_selected_evidence_enters_model_payload_and_reviewer(self):
        api = Mock(return_value=response(draft()))
        result = generate_answer(sample(), api_call=api, key_provider=lambda:'fake-test-key')
        self.assertEqual(result['status'], 'ANSWERED')
        sent = json.loads(api.call_args.args[0]['messages'][1]['content'])
        self.assertEqual([e['chunk_id'] for e in sent['EVIDENCE']], sample()['selected_chunk_ids'])
        review = review_answer(result, dry_run=True)
        self.assertEqual(review['decision'], 'READY_FOR_REVIEW')
        self.assertNotIn('fake-test-key', json.dumps(result))

    def test_unselected_citation_is_rejected(self):
        value = draft()
        value['claims'][0]['source_ids'] = ['S4']
        value['claims'][0]['evidence_quotes'][0]['source_id'] = 'S4'
        api = Mock(return_value=response(value))
        result = generate_answer(sample(), api_call=api, key_provider=lambda:'key')
        self.assertEqual(result['error']['code'], 'CITATION_VALIDATION_FAILED')
        self.assertEqual(api.call_count, 1)

    def test_plain_v2_response_supported(self):
        result = generate_answer(sample()['retrieval'], dry_run=True)
        self.assertEqual(result['status'], 'READY_FOR_GENERATION')
        self.assertEqual(result['m4_input']['candidate_count'], 5)

    def test_unknown_selected_id(self):
        value = sample(); value['selected_chunk_ids'][0] = 'a'*64
        self.blocked(value)

    def test_duplicate_and_reordered_ids(self):
        for mode in ('duplicate','reverse'):
            value = sample()
            if mode == 'duplicate': value['selected_chunk_ids'].append(value['selected_chunk_ids'][0])
            else: value['selected_chunk_ids'].reverse()
            self.blocked(value)

    def test_modified_context_or_missing_selection(self):
        value = sample(); value['context'] += '\nInjected content.'
        self.blocked(value)
        value = sample(); del value['selected_chunk_ids']
        self.blocked(value)

    def test_empty_selection_not_confused_with_no_retrieval_results(self):
        value = sample(); value.update(selected_chunk_ids=[], context='', context_tokens=0)
        self.blocked(value, 'EMPTY_SELECTED_CONTEXT')

    def test_text_hash_and_source_metadata(self):
        for field in ('text', 'url'):
            value = sample()['retrieval']
            if field == 'text': value['results'][0]['text'] += ' tampered'
            else: value['results'][0]['citation']['url'] = 'https://other.example/article'
            self.blocked(value)

    def test_bad_config_rank_scores_and_provenance(self):
        variants = []
        v = sample()['retrieval']; v['config']['top_k'] = True; variants.append(v)
        v = sample()['retrieval']; v['results'][0]['rank'] = 2; variants.append(v)
        v = sample()['retrieval']; v['results'][0]['scores']['rrf'] = -1; variants.append(v)
        v = sample()['retrieval']; v['results'][0]['scores']['similarity'] = 0; variants.append(v)
        v = sample()['retrieval']; v['results'][0]['retrieved_by'] = ['dense','dense']; variants.append(v)
        v = sample()['retrieval']; v['config']['mode'] = 'bm25'; variants.append(v)
        for v in variants: self.blocked(v)

    def test_extra_fields_invalid_dates_and_token_types(self):
        v = sample()['retrieval']; v['unapproved_field'] = 1; self.blocked(v)
        v = sample()['retrieval']; v['results'][0]['citation']['published_at_utc'] = '2026-02-30T00:00:00Z'; self.blocked(v)
        v = sample(); v['context_tokens'] = True; self.blocked(v)

    def test_v2_early_error_preserved_without_api(self):
        v = sample()['retrieval']
        v.update(status='ERROR', query='', retrieval_query='', index=None, results=[],
                 config={'mode':'hybrid'}, error={'code':'INVALID_QUERY','message':'Question is empty.'})
        api, key = Mock(), Mock()
        result = generate_answer(v, api_call=api, key_provider=key)
        self.assertEqual(result['error']['code'], 'RETRIEVAL_ERROR')
        self.assertEqual(result['upstream_error'], v['error'])
        self.assertEqual(result['retrieval_config'], {'mode':'hybrid'})
        api.assert_not_called(); key.assert_not_called()

    def test_v2_no_evidence_refusal_in_english(self):
        v = sample()['retrieval']; v.update(status='NO_EVIDENCE', results=[])
        result = generate_answer(v)
        self.assertEqual(result['status'], 'INSUFFICIENT_SOURCES')
        self.assertEqual(result['generation']['calls'], [])
        self.assertNotRegex(result['answer'], r'[\u3400-\u9fff]')

    def test_generated_chinese_prose_blocked(self):
        v = draft(); v['claims'][0]['text'] = '\u9519\u8bef\u7684\u8bed\u8a00'
        result = generate_answer(sample(), api_call=Mock(return_value=response(v)), key_provider=lambda:'key')
        self.assertEqual(result['error']['code'], 'OUTPUT_LANGUAGE_MISMATCH')
        self.assertEqual(result['answer'], '')

    def test_language_repair_still_bounded_to_two_calls(self):
        bad = draft(); bad['claims'][0]['text'] = '\u4e2d\u6587'
        api = Mock(side_effect=[response(bad), response(draft())])
        result = generate_answer(sample(), api_call=api, key_provider=lambda:'key', repair_once=True)
        self.assertEqual(result['status'], 'ANSWERED')
        self.assertEqual(api.call_count, 2)

    def test_historical_partial_record_remains_readable(self):
        v = draft(); v.update(status='PARTIAL', missing_information=['\u62a4\u7167\u53f7\u7801'])
        # Build an English current record, then reconstruct the historical renderer.
        v['missing_information'] = ['Passport numbers']
        saved = generate_answer(sample(), api_call=Mock(return_value=response(v)), key_provider=lambda:'key')
        saved['implementation_version'] = 'm5-integration-v0.1'
        saved['answer'] = saved['claims'][0]['text'] + ' [S1]\n\u8d44\u6599\u7f3a\u53e3\uff1aPassport numbers'
        self.assertEqual(review_answer(saved, dry_run=True)['decision'], 'READY_FOR_REVIEW')

    def test_prompts_and_active_runtime_text_are_english(self):
        for file in (ROOT/'scripts/m5_generation').rglob('*'):
            if file.suffix in {'.py', '.txt'}:
                self.assertNotRegex(file.read_text(encoding='utf-8'), r'[\u3400-\u9fff]', str(file))

    def test_review_reasons_must_not_be_chinese(self):
        from scripts.m5_generation.support import validate_review
        from scripts.m5_generation.api import M5Error
        judged = {'claim_reviews': [], 'answer_review': {'recommended_status':'INSUFFICIENT_SOURCES',
                  'status_appropriate':True,'missing_information_accurate':True,
                  'no_unresolved_conflicts':True,'reason':'\u4e2d\u6587'}}
        prepared = {'DRAFT': {'claims':[], 'status':'INSUFFICIENT_SOURCES'}}
        with self.assertRaises(M5Error) as caught:
            validate_review(judged, prepared)
        self.assertEqual(caught.exception.code, 'OUTPUT_LANGUAGE_MISMATCH')

    def test_exact_quotes_are_exempt_from_language_guard(self):
        import hashlib
        v = sample()['retrieval']
        quote = '\u8fd9\u662f\u539f\u6587'
        v['results'][0]['text'] = quote
        v['results'][0]['text_sha256'] = hashlib.sha256(quote.encode('utf-8')).hexdigest()
        answer = draft(); answer['claims'][0]['evidence_quotes'][0]['quote'] = quote
        result = generate_answer(v, api_call=Mock(return_value=response(answer)), key_provider=lambda:'key')
        self.assertEqual(result['status'], 'ANSWERED')
        self.assertEqual(result['claims'][0]['evidence_quotes'][0]['quote'], quote)


if __name__ == '__main__':
    unittest.main()
