"""Strict parsing is preserved; diagnostics must not trigger retries or acceptance."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from scripts.m5_generation.api import M5Error, strict_json, parse_envelope, call_api
from scripts.m5_generation.generator import generate_answer
from scripts.m5_generation.support import review_answer
from scripts.m5_generation.pipeline import run_pipeline

ROOT=Path(__file__).resolve().parents[1]


def fixture():
    return json.loads((ROOT/'examples/m5/retrieval_ok.json').read_text(encoding='utf-8'))


def envelope(text):
    return {'model':'mock','choices':[{'finish_reason':'stop','message':{'content':text}}],
            'usage':{'prompt_tokens':10,'completion_tokens':5}}


def valid_draft():
    return json.dumps({'status':'ANSWERED','claims':[{'text':'At least 35 Australians are missing in Nepal.',
                       'source_ids':['S1'],'evidence_quotes':[{'source_id':'S1','quote':'at least 35 Australians missing in Nepal'}]}],
                       'missing_information':[]})


class DiagnosticsTests(unittest.TestCase):
    def test_syntax_location_and_exact_excerpt(self):
        raw='{\n"claim_reviews": [}\n'
        with self.assertRaises(M5Error) as caught:
            parse_envelope(envelope(raw))
        d=caught.exception.diagnostics
        self.assertEqual(d['source'],'model_content');self.assertEqual(d['reason'],'syntax_error')
        self.assertEqual(d['line'],2);self.assertEqual(d['model_text_excerpt'],raw)
        self.assertEqual(d['text_sha256'],hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(d['finish_reason'],'stop')

    def test_duplicate_keys_still_rejected(self):
        with self.assertRaises(M5Error) as caught:
            strict_json('{"a":1,"a":2}')
        self.assertEqual(caught.exception.diagnostics['reason'],'duplicate_key')

    def test_nonfinite_numbers_still_rejected(self):
        for raw in ['{"n":NaN}','{"n":Infinity}','{"n":1e999}']:
            with self.assertRaises(M5Error) as caught: strict_json(raw)
            self.assertEqual(caught.exception.diagnostics['reason'],'nonfinite_number')

    def test_code_fences_and_trailing_prose_are_not_silently_repaired(self):
        for raw in ['```json\n{}\n```','{} approved','{"a":1,}']:
            with self.assertRaises(M5Error): parse_envelope(envelope(raw))

    def test_excerpt_bounded(self):
        raw='x'*20000
        with self.assertRaises(M5Error) as caught: parse_envelope(envelope(raw))
        self.assertTrue(caught.exception.diagnostics['excerpt_truncated'])
        self.assertEqual(len(caught.exception.diagnostics['model_text_excerpt']),16384)

    def test_nonmodel_json_does_not_capture_content(self):
        with self.assertRaises(M5Error) as caught: strict_json('private malformed data',source='api_response_body')
        self.assertNotIn('model_text_excerpt',caught.exception.diagnostics)
        self.assertNotIn('private',json.dumps(caught.exception.diagnostics))

    def test_transport_body_diagnostic_has_no_key(self):
        with patch('scripts.m5_generation.api.urllib.request.build_opener') as builder:
            builder.return_value.open.return_value.__enter__.return_value.read.return_value=b'not JSON'
            with self.assertRaises(M5Error) as caught: call_api({},'offline-secret-key')
        self.assertEqual(caught.exception.diagnostics['source'],'api_response_body')
        self.assertNotIn('offline-secret-key',json.dumps(caught.exception.diagnostics))

    def test_review_failure_keeps_diagnostics_no_retry(self):
        a=generate_answer(fixture(),api_call=Mock(return_value=envelope(valid_draft())),key_provider=lambda:'fake')
        api=Mock(return_value=envelope('{broken review'))
        r=review_answer(a,api_call=api,key_provider=lambda:'fake')
        self.assertEqual(r['decision'],'ERROR');self.assertEqual(api.call_count,1)
        self.assertEqual(r['error']['diagnostics']['model_text_excerpt'],'{broken review')
        self.assertFalse(r['publication_ready'])

    def test_pipeline_error_remains_closed_with_two_calls(self):
        api=Mock(side_effect=[envelope(valid_draft()),envelope('{broken review')])
        r=run_pipeline(fixture(),api_call=api,key_provider=lambda:'fake')
        self.assertEqual(r['status'],'ERROR');self.assertEqual(api.call_count,2)
        self.assertEqual(r['answer'],'');self.assertFalse(r['repair_used'])
        self.assertEqual(r['error']['diagnostics']['source'],'model_content')

    def test_generator_failure_keeps_diagnostics(self):
        r=generate_answer(fixture(),api_call=Mock(return_value=envelope('bad')),key_provider=lambda:'fake')
        self.assertEqual(r['status'],'ERROR')
        self.assertEqual(r['error']['diagnostics']['reason'],'syntax_error')


if __name__=='__main__':
    unittest.main()
