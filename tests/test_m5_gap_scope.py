"""Offline gate tests with mocked judgments; these do not measure model accuracy."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock
from scripts.m5_generation.pipeline import run_pipeline

ROOT = Path(__file__).resolve().parents[1]

def envelope(content):
    return {'model':'offline-test', 'choices':[{'finish_reason':'stop',
        'message':{'content':json.dumps(content)}}],
        'usage':{'prompt_tokens':100,'completion_tokens':30}}

def refusal(extra=False):
    gap = "The supplied reports do not provide the missing travellers' passport numbers."
    if extra:
        gap += ' They only give counts of at least 34, later 39, and then 38 missing.'
    return {'status':'INSUFFICIENT_SOURCES','claims':[], 'missing_information':[gap]}

def judgment(accurate):
    return {'claim_reviews':[], 'answer_review':{
        'recommended_status':'INSUFFICIENT_SOURCES', 'status_appropriate':True,
        'missing_information_accurate':accurate, 'no_unresolved_conflicts':True,
        'reason':'The requested passport numbers are absent.' if accurate else
                 'The gap contains unnecessary counts; remove that background.'}}

class GapScopeTests(unittest.TestCase):
    def run_case(self, outputs):
        retrieval = json.loads((ROOT/'examples/m5/retrieval_ok.json').read_text(encoding='utf-8'))
        retrieval['query'] = "What are the missing travellers' passport numbers?"
        retrieval['retrieval_query'] = retrieval['query']
        api = Mock(side_effect=[envelope(item) for item in outputs])
        result = run_pipeline(retrieval, api_call=api, key_provider=lambda:'offline-only')
        self.assertFalse(result['publication_ready'])
        return result, api

    def test_gap_failure_repairs_even_with_no_claims(self):
        result, api = self.run_case([refusal(True), judgment(False), refusal(), judgment(True)])
        self.assertEqual(result['status'], 'INSUFFICIENT_SOURCES')
        self.assertEqual(result['gate'], 'AUTOMATIC_REVIEW_PASSED')
        self.assertTrue(result['repair_used'])
        self.assertEqual(api.call_count, 4)
        self.assertEqual(result['attempts'][0]['review']['decision'], 'FAIL')
        first = json.loads(api.call_args_list[0].args[0]['messages'][1]['content'])
        repaired = json.loads(api.call_args_list[2].args[0]['messages'][1]['content'])
        self.assertEqual(first['EVIDENCE'], repaired['EVIDENCE'])
        self.assertFalse(repaired['REVISION_FEEDBACK']['answer_review']['missing_information_accurate'])
        self.assertEqual(result['missing_information'], refusal()['missing_information'])

    def test_gap_failure_after_repair_blocks_display(self):
        result, api = self.run_case([refusal(True), judgment(False), refusal(True), judgment(False)])
        self.assertEqual(result['gate'], 'BLOCKED')
        self.assertEqual(result['status'], 'ERROR')
        self.assertEqual(result['error']['code'], 'REVIEW_REJECTED')
        self.assertEqual(result['answer'], '')
        self.assertIsNone(result['answer_record'])
        self.assertEqual(api.call_count, 4)

    def test_concise_refusal_needs_no_repair(self):
        result, api = self.run_case([refusal(), judgment(True)])
        self.assertEqual(result['status'], 'INSUFFICIENT_SOURCES')
        self.assertFalse(result['repair_used'])
        self.assertEqual(api.call_count, 2)

if __name__ == '__main__':
    unittest.main()
