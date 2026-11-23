"""Offline malformed-review diagnostics; cases are synthetic, not recovered API text."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from contextlib import redirect_stdout

from scripts.m5_generation.support import review_answer
from scripts.m5_generation.review_cli import main
from scripts.m5_generation.public_contracts import validation_report_from_review
from scripts.m5_generation.pipeline import run_pipeline
from test_m5_support import record, passing, envelope
from test_m5_pipeline import fixture, draft

class ReviewShapeDiagnosticsTests(unittest.TestCase):
    def review(self, judged):
        original=record()
        api=Mock(return_value=envelope(judged))
        result=review_answer(original,api_call=api,key_provider=lambda:'offline-key')
        self.assertEqual(api.call_count,1)
        self.assertEqual(result['decision'],'ERROR')
        self.assertEqual(result['error']['code'],'INVALID_JUDGE_OUTPUT')
        self.assertFalse(result['publication_ready'])
        return original,result,result['error']['diagnostics']

    def test_missing_each_overall_field_is_reported(self):
        for field in passing()['answer_review']:
            with self.subTest(field=field):
                judged=passing();del judged['answer_review'][field]
                _,_,details=self.review(judged)
                self.assertEqual(details['location'],'$.answer_review')
                self.assertEqual(details['missing_fields'],[field])
                self.assertEqual(details['unexpected_field_count'],0)

    def test_extra_scope_fields_rejected_not_silently_removed(self):
        judged=passing()
        judged['answer_review'].update(scope_role='unnecessary',relevance_reason='Synthetic misplaced fields.')
        _,_,details=self.review(judged)
        self.assertEqual(details['unexpected_known_fields'],['relevance_reason','scope_role'])
        self.assertEqual(details['missing_fields'],[])
        self.assertEqual(details['unexpected_field_count'],2)

    def test_nonobject_overall_review_identifies_type(self):
        for value,kind in [(None,'NoneType'),([],'list'),('wrong','str')]:
            judged=passing();judged['answer_review']=value
            _,_,details=self.review(judged)
            self.assertEqual(details['actual_type'],kind)
            self.assertEqual(len(details['missing_fields']),5)

    def test_no_arbitrary_field_names_or_model_prose_in_diagnostics(self):
        judged=passing()
        private_name='synthetic-private-field-ABC123'
        private_value='Synthetic private diagnostic body, never a real key.'
        judged['answer_review'][private_name]=private_value
        _,result,details=self.review(judged)
        self.assertEqual(details['unrecognized_field_count'],1)
        self.assertFalse(details['content_values_saved'])
        self.assertNotIn(private_name,json.dumps(result))
        self.assertNotIn(private_value,json.dumps(result))

    def test_top_claim_and_citation_paths(self):
        for location in ('top','claim','citation'):
            judged=passing()
            if location=='top':judged['decision']='PASS'
            elif location=='claim':del judged['claim_reviews'][0]['scope_role']
            else:del judged['claim_reviews'][0]['citation_reviews'][0]['reason']
            _,_,details=self.review(judged)
            expected={'top':'$','claim':'$.claim_reviews[0]',
                      'citation':'$.claim_reviews.C1.citation_reviews[0]'}[location]
            self.assertEqual(details['location'],expected)

    def test_error_report_remains_schema_valid(self):
        judged=passing();judged['answer_review']['scope_role']='unnecessary'
        original,result,_=self.review(judged)
        report=validation_report_from_review(original,result)
        self.assertEqual(report['decision'],'ERROR')
        self.assertEqual(report['claim_reviews'],[])
        self.assertEqual(report['error']['diagnostics']['location'],'$.answer_review')

    def test_cli_prints_field_diagnostics_and_saves_error(self):
        judged=passing();del judged['answer_review']['reason']
        original,result,_=self.review(judged)
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'answer.json';output=Path(tmp)/'review.json'
            source.write_text(json.dumps(original),encoding='utf-8')
            before=source.read_bytes()
            stdout=io.StringIO()
            with patch('sys.argv',['review_cli','--input',str(source),'--output',str(output)]), \
                 patch('scripts.m5_generation.review_cli.review_answer',return_value=result), redirect_stdout(stdout):
                code=main()
            self.assertEqual(code,1)
            self.assertIn('Object: $.answer_review',stdout.getvalue())
            self.assertIn('Missing fields: reason',stdout.getvalue())
            self.assertEqual(json.loads(output.read_text())['decision'],'ERROR')
            self.assertEqual(source.read_bytes(),before)

    def test_pipeline_does_not_spend_repair_on_malformed_review(self):
        judged=passing();del judged['answer_review']['status_appropriate']
        api=Mock(side_effect=[envelope(draft()),envelope(judged)])
        result=run_pipeline(fixture(),api_call=api,key_provider=lambda:'offline-key')
        self.assertEqual(api.call_count,2)
        self.assertEqual(result['gate'],'ERROR')
        self.assertFalse(result['repair_used'])
        self.assertEqual(result['answer'],'')
        self.assertEqual(result['error']['diagnostics']['missing_fields'],['status_appropriate'])

if __name__=='__main__':
    unittest.main()
