"""Offline contract regressions. Mock verdicts do not measure judge accuracy."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

from scripts.m5_generation.api import M5Error
from scripts.m5_generation.pipeline import run_pipeline
from scripts.m5_generation.public_contracts import (
    CONTRACTS, schema_validator, validate_schema, validate_answer,
    evidence_bundle_from_record, validate_evidence_bundle,
    validation_report_from_review, export_pipeline_contracts)
from test_m5_pipeline import fixture, draft, judge, envelope

ROOT = Path(__file__).resolve().parents[1]


def sample(status='ANSWERED', passing=True):
    d = draft(status)
    j = judge(passing, status)
    if status == 'INSUFFICIENT_SOURCES':
        d = {'status': status, 'claims': [], 'missing_information': ['Passport numbers']}
        j['claim_reviews'] = []
    return run_pipeline(fixture(), api_call=Mock(side_effect=[envelope(d), envelope(j)]),
                        key_provider=lambda: 'mock-secret', allow_repair=False)


class PublicContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.success = sample()

    def fresh(self):
        return copy.deepcopy(self.success)

    def test_all_schema_definitions_and_success_export(self):
        for name in CONTRACTS:
            self.assertIsNotNone(schema_validator(name))
        result = export_pipeline_contracts(self.fresh())
        self.assertEqual(len(result), 7)
        self.assertEqual(result['validation_report.json']['decision'], 'PASS')
        self.assertFalse(result['final_answer.json']['publication_ready'])
        self.assertNotIn('mock-secret', json.dumps(result))

    def test_partial_and_semantic_refusal(self):
        for status in ('PARTIAL', 'INSUFFICIENT_SOURCES'):
            with self.subTest(status=status):
                result = export_pipeline_contracts(sample(status))
                self.assertEqual(result['final_answer.json']['status'], status)
                self.assertEqual(result['validation_report.json']['decision'], 'PASS')

    def test_local_preflight_and_empty_retrieval_and_system_error(self):
        for name, status in [('retrieval_ok', 'READY_FOR_PIPELINE'),
                             ('retrieval_no_evidence', 'INSUFFICIENT_SOURCES'),
                             ('retrieval_error', 'ERROR')]:
            with self.subTest(name=name):
                api, key = Mock(), Mock()
                p = run_pipeline(fixture(name), dry_run=True, api_call=api, key_provider=key)
                result = export_pipeline_contracts(p)
                self.assertEqual(p['status'], status)
                api.assert_not_called(); key.assert_not_called()
                if status == 'READY_FOR_PIPELINE':
                    self.assertEqual(list(result), ['evidence_bundle.json'])
                elif status == 'ERROR':
                    self.assertEqual(result['final_answer.json']['answer'], '')
                else:
                    self.assertEqual(result['validation_report.json']['decision'], 'NOT_RUN')

    def test_failed_semantic_review_remains_blocked(self):
        result = export_pipeline_contracts(sample(passing=False))
        self.assertEqual(result['final_answer.json']['status'], 'ERROR')
        self.assertEqual(result['attempt_1/validation_report.json']['decision'], 'FAIL')

    def test_invalid_review_json_stays_error(self):
        p = run_pipeline(fixture(), api_call=Mock(side_effect=[envelope(draft()), envelope('not JSON')]),
                         key_provider=lambda: 'mock-secret')
        result = export_pipeline_contracts(p)
        self.assertEqual(result['final_answer.json']['status'], 'ERROR')
        self.assertEqual(result['attempt_1/validation_report.json']['decision'], 'ERROR')

    def test_generation_error_and_repair(self):
        for responses, expected in [([envelope('bad'), envelope('bad')], 'ERROR'),
                    ([envelope('bad'), envelope(draft()), envelope(judge())], 'ANSWERED'),
                    ([M5Error('API_TIMEOUT', 'Mock timeout.')], 'ERROR')]:
            with self.subTest(expected=expected, calls=len(responses)):
                p = run_pipeline(fixture(), api_call=Mock(side_effect=responses), key_provider=lambda: 'mock-secret')
                self.assertEqual(export_pipeline_contracts(p)['final_answer.json']['status'], expected)

    def test_draft_schema_rejects_errors_extras_and_invalid_state_claims(self):
        for change in ({'status':'ERROR'}, {'extra':'text'}, {'claims':[]}, {'missing_information':['gap']}):
            d = draft(); d.update(change)
            with self.subTest(change=change), self.assertRaises(M5Error):
                validate_schema('generation_draft.v1', d)

    def test_unknown_citation_and_wrong_quote_offsets(self):
        for field in ('source_id', 'offset'):
            a = self.fresh()['answer_record']
            if field == 'source_id':
                a['claims'][0]['source_ids'] = ['S99']
            else:
                a['claims'][0]['located_quotes'][0]['char_start'] += 1
            with self.subTest(field=field), self.assertRaises(M5Error):
                validate_answer(a)

    def test_render_and_source_metadata_tampering(self):
        for field in ('answer', 'url'):
            a = self.fresh()['answer_record']
            if field == 'answer':
                a['answer'] += '\nAdditional unsupported text.'
            else:
                a['sources'][0]['url'] = 'https://example.org/fake'
            with self.subTest(field=field), self.assertRaises(M5Error):
                validate_answer(a)

    def test_bundle_hash_duplicate_labels_and_budget(self):
        original = evidence_bundle_from_record(self.fresh()['answer_record'])
        for field in ('hash', 'label', 'budget'):
            b = copy.deepcopy(original)
            if field == 'hash':
                b['evidence'][0]['text'] += ' changed'
            elif field == 'label':
                b['evidence'][1]['source_id'] = 'S1'
            else:
                b['token_budget']['total_tokens_reserved'] += 1
            with self.subTest(field=field), self.assertRaises(M5Error):
                validate_evidence_bundle(b)

    def test_trusted_bundle_binding(self):
        a = self.fresh()['answer_record']
        b = evidence_bundle_from_record(a)
        b['query'] += ' changed'
        with self.assertRaises(M5Error):
            validate_answer(a, evidence_bundle=b)

    def test_review_binding_hash_snapshot_and_decision(self):
        for field in ('input_object_sha256', 'input_snapshot', 'decision'):
            p = self.fresh(); a = p['answer_record']; r = p['attempts'][0]['review']
            if field == 'input_object_sha256': r[field] = '0'*64
            elif field == 'input_snapshot': r[field]['query'] += ' changed'
            else: r[field] = 'FAIL'
            with self.subTest(field=field), self.assertRaises(M5Error):
                validation_report_from_review(a, r)

    def test_uncertainty_cannot_be_promoted_to_pass(self):
        p = self.fresh(); r = p['attempts'][0]['review']
        r['claim_reviews'][0]['verdict'] = 'uncertain'
        with self.assertRaises(M5Error):
            validation_report_from_review(p['answer_record'], r)

    def test_no_review_is_not_pass(self):
        a = self.fresh()['answer_record']
        self.assertEqual(validation_report_from_review(a)['decision'], 'NOT_RUN')
        self.assertEqual(validate_answer(a)['support'], 'unchecked')

    def test_pipeline_cannot_change_reviewed_answer_or_publish(self):
        for field in ('answer', 'publication_ready'):
            p = self.fresh(); p[field] = True if field == 'publication_ready' else 'Other answer'
            with self.subTest(field=field), self.assertRaises(M5Error):
                export_pipeline_contracts(p)

    def test_saved_m4_selection_binding(self):
        original = json.loads((ROOT/'documents/m4/m5_hybrid_C_example.json').read_text(encoding='utf-8'))
        p = run_pipeline(original, dry_run=True)
        preview = p['preview']
        evidence_bundle_from_record(preview)
        preview['evidence'][0]['citation']['title'] += ' forged'
        with self.assertRaises(M5Error):
            evidence_bundle_from_record(preview)

    def test_cli_export_no_overwrite_and_original_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'input.json'; out = Path(temp)/'export'
            path.write_text(json.dumps(self.fresh()), encoding='utf-8'); before = path.read_bytes()
            cmd = [sys.executable, '-B', '-X', 'utf8', '-m', 'scripts.m5_generation.contracts_cli',
                   '--pipeline', str(path), '--output-dir', str(out)]
            p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout+p.stderr)
            summary = json.loads((out/'summary.json').read_text())
            self.assertEqual(summary['new_api_calls'], 0)
            self.assertFalse(summary['semantic_reassessment_performed'])
            p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0); self.assertIn('OUTPUT_EXISTS', p.stdout)
            self.assertEqual(path.read_bytes(), before)

    def test_nonfinite_values_rejected(self):
        a = self.fresh()['answer_record']; a['generation']['cost'] = float('nan')
        with self.assertRaises(M5Error): validate_answer(a)


if __name__ == '__main__':
    unittest.main()
