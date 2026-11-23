"""Offline G0/G1/G2 driver checks. The mock model does not score answer quality."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.m5_generation.api import M5Error
from scripts.m5_generation.pipeline import run_pipeline
from scripts.m6_evaluation.check_experiment_plan import protocol_problems
from scripts.m6_evaluation.protocol_driver import comparison_plan, main, run_protocol_item, run_saved_protocol

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return json.loads((ROOT / 'examples/m5/retrieval_ok.json').read_text(encoding='utf-8'))


def draft():
    return {'status': 'ANSWERED', 'claims': [{'text': 'At least 35 Australians are missing in Nepal.',
            'source_ids': ['S1'], 'evidence_quotes': [{'source_id': 'S1', 'quote': 'at least 35 Australians missing in Nepal'}]}],
            'missing_information': []}


def judge(passing=True):
    return {'claim_reviews': [{'claim_id': 'C1', 'verdict': 'supported' if passing else 'unsupported', 'relevant': True,
            'scope_role': 'direct_answer', 'relevance_reason': 'This answers the requested count.',
            'reason': 'Mock review.', 'citation_reviews': [{'source_id': 'S1',
            'verdict': 'supports' if passing else 'unrelated',
            'reason': 'Mock citation review.'}]}],
            'answer_review': {'recommended_status': 'ANSWERED', 'status_appropriate': True,
            'missing_information_accurate': True, 'no_unresolved_conflicts': True, 'reason': 'Mock scope review.'}}


def envelope(content):
    return {'model': 'offline-test', 'choices': [{'finish_reason': 'stop', 'message': {
        'content': content if isinstance(content, str) else json.dumps(content)}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}


class ProtocolDriverTests(unittest.TestCase):
    def drive(self, protocol, responses):
        api = Mock(side_effect=responses)
        result = run_protocol_item(fixture(), protocol, model='deepseek-flash', api_call=api,
                                   key_provider=lambda: 'offline-secret')
        self.assertNotIn('offline-secret', json.dumps(result))
        return result, api

    def test_three_protocols_share_model_and_evidence_and_diverge(self):
        g0, g0_api = self.drive('G0', [envelope({'answer': 'At least 35 Australians are missing in Nepal.'})])
        g1, g1_api = self.drive('G1', [envelope(draft())])
        g2, g2_api = self.drive('G2', [envelope(draft()), envelope(judge())])
        g1_ids = [item['chunk_id'] for item in g1['answer_record']['evidence']]
        g2_ids = [item['chunk_id'] for item in g2['answer_record']['evidence']]
        self.assertEqual(g0['evidence_chunk_ids'], g1_ids)
        self.assertEqual(g1_ids, g2_ids)
        self.assertEqual(g0_api.call_args.args[0]['model'], g1_api.call_args.args[0]['model'])
        self.assertEqual(g1_api.call_args.args[0]['model'], g2_api.call_args.args[0]['model'])
        self.assertEqual(protocol_problems('G0', g0), [])
        self.assertEqual(protocol_problems('G1', g1), [])
        self.assertEqual(protocol_problems('G2', g2), [])
        self.assertTrue(protocol_problems('G1', g0))
        self.assertTrue(protocol_problems('G0', g1))
        self.assertTrue(protocol_problems('G2', g1))
        self.assertEqual(g0_api.call_count, 1)
        self.assertEqual(g1_api.call_count, 1)
        self.assertEqual(g2_api.call_count, 2)
        self.assertNotIn('[S1]', g0['answer'])
        self.assertEqual(g0['gate'], 'PROMPT_CITATION_ONLY')
        self.assertEqual(g1['gate'], 'HARD_VALIDATION_PASSED')
        self.assertEqual(g2['gate'], 'AUTOMATIC_REVIEW_PASSED')
        self.assertIsNone(g0['attempts'][0]['review'])
        self.assertIsNone(g1['attempts'][0]['review'])
        self.assertEqual(g2['attempts'][0]['review']['decision'], 'PASS')

    def test_g1_validation_failure_does_not_repair_or_review(self):
        result, api = self.drive('G1', [envelope('not json')])
        self.assertEqual(result['gate'], 'BLOCKED')
        self.assertEqual(result['answer'], '')
        self.assertEqual(api.call_count, 1)
        self.assertEqual(protocol_problems('G1', result), [])
        self.assertTrue(protocol_problems('G0', result))

    def test_dry_run_no_repair_and_stripped_review_are_not_g0_or_g1(self):
        dry = run_protocol_item(fixture(), 'G0', dry_run=True, api_call=Mock(), key_provider=lambda: 'offline-secret')
        self.assertEqual(dry['gate'], 'NOT_RUN')
        self.assertTrue(protocol_problems('G0', dry))
        reviewed, _api = self.drive('G2', [envelope(draft()), envelope(judge())])
        no_repair = run_pipeline(fixture(), allow_repair=False, api_call=Mock(side_effect=[envelope(draft()), envelope(judge())]),
                                 key_provider=lambda: 'offline-secret')
        self.assertEqual(no_repair['gate'], 'AUTOMATIC_REVIEW_PASSED')
        self.assertTrue(protocol_problems('G1', no_repair))
        stripped = json.loads(json.dumps(reviewed))
        for call in stripped['api_calls']:
            if call['stage'] in {'review', 'repair_review'}:
                call['stage'] = 'generation'
        for attempt in stripped['attempts']:
            attempt['review'] = None
        stripped['protocol'] = 'G1'
        stripped['protocol_binding']['protocol'] = 'G1'
        stripped['protocol_binding']['automatic_review'] = False
        stripped['protocol_binding']['repair'] = False
        stripped['gate'] = 'HARD_VALIDATION_PASSED'
        self.assertTrue(protocol_problems('G1', stripped))

    def test_plan_does_not_generate(self):
        plan = comparison_plan(ROOT / 'm5_runs/d_dev_retrieval/C_hybrid_k5_skip', 'deepseek-flash')
        self.assertEqual(plan['protocols'], ['G0', 'G1', 'G2'])
        self.assertFalse(plan['generated'])
        self.assertEqual(plan['official_scores'], '0/0')
        self.assertEqual(plan['results_sha256'], '15d8e6b369c24c2bfcc3f73d2ad3159449df83768d0af07ee88ed64829ceb9ee')
        self.assertFalse(plan['dry_run_is_protocol'])
        self.assertFalse(plan['no_repair_is_g1'])
        self.assertFalse(plan['strip_review_is_g1'])

    def saved_batch(self, protocol, api, items):
        manifest = {'results_sha256': 'a' * 64, 'input_sha256': 'b' * 64}
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'run'
            with patch('scripts.m6_evaluation.protocol_driver.load_a_run', return_value=(manifest, items)):
                result = run_saved_protocol(Path('unused'), output, protocol, generate=True, api_call=api,
                                            key_provider=lambda: 'offline-secret')
            saved = json.loads((output / 'run.json').read_text())
            rows = [json.loads(line) for line in (output / 'predictions.jsonl').read_text().splitlines()]
            pipelines = [json.loads((output / row['pipeline_file']).read_text()) for row in rows]
            return result, saved, rows, pipelines

    def two_items(self):
        first = fixture()
        second = json.loads(json.dumps(first))
        second['request_id'] = 'fixture-answerable-002'
        return [{'record': {'id': 'q1', 'line': 1}, 'packed': first},
                {'record': {'id': 'q2', 'line': 2}, 'packed': second}]

    def test_interrupt_checkpoints_the_inflight_call(self):
        items = self.two_items()
        seen = {}

        def interrupt(payload, key):
            self.assertTrue(seen['pipeline'].is_file())
            pipeline = json.loads(seen['pipeline'].read_text())
            manifest = json.loads(seen['run'].read_text())
            self.assertEqual(pipeline['api_calls'][0]['state'], 'STARTING')
            self.assertGreaterEqual(manifest['api_requests'], 1)
            raise KeyboardInterrupt()

        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'run'
            seen['pipeline'] = output / 'item_0001' / 'pipeline.json'
            seen['run'] = output / 'run.json'
            manifest = {'results_sha256': 'a' * 64, 'input_sha256': 'b' * 64}
            with patch('scripts.m6_evaluation.protocol_driver.load_a_run', return_value=(manifest, items)):
                result = run_saved_protocol(Path('unused'), output, 'G0', generate=True, api_call=interrupt,
                                            key_provider=lambda: 'offline-secret')
            saved = json.loads((output / 'run.json').read_text())
            rows = [json.loads(line) for line in (output / 'predictions.jsonl').read_text().splitlines()]
            pipeline = json.loads((output / rows[0]['pipeline_file']).read_text())
        self.assertEqual(result['status'], 'COMPLETED_WITH_ERRORS')
        self.assertEqual(saved['api_requests'], 1)
        self.assertEqual(pipeline['api_calls'][0]['state'], 'INTERRUPTED_OUTCOME_UNKNOWN')
        self.assertEqual(pipeline['error']['code'], 'CANCELLED')
        self.assertEqual(rows[1]['error']['code'], 'BATCH_ABORTED')
        self.assertEqual(rows[1]['repair_used'], False)

    def test_escaping_interrupt_keeps_the_batch_total_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'run'
            manifest = {'results_sha256': 'a' * 64, 'input_sha256': 'b' * 64}
            with patch('scripts.m6_evaluation.protocol_driver.load_a_run', return_value=(manifest, self.two_items())):
                with patch('scripts.m6_evaluation.protocol_driver.run_protocol_item', side_effect=KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt):
                        run_saved_protocol(Path('unused'), output, 'G1', generate=True, api_call=Mock(),
                                           key_provider=lambda: 'offline-secret')
            saved = json.loads((output / 'run.json').read_text())
        self.assertEqual(saved['status'], 'INTERRUPTED')
        self.assertIsNone(saved['api_requests'])
        self.assertIsNone(saved['billing'])

    def test_auth_failure_stops_later_paid_calls_and_is_not_complete(self):
        calls = {'n': 0}

        def deny(payload, key):
            calls['n'] += 1
            raise M5Error('HTTP_401', 'Authentication failed.')

        result, saved, rows, pipelines = self.saved_batch('G1', deny, self.two_items())
        self.assertEqual(calls['n'], 1)
        self.assertEqual(saved['status'], 'COMPLETED_WITH_ERRORS')
        self.assertEqual(rows[0]['status'], 'ERROR')
        self.assertEqual(rows[0]['error']['code'], 'HTTP_401')
        self.assertEqual(rows[1]['error']['code'], 'BATCH_ABORTED')
        self.assertEqual(pipelines[1]['api_calls'], [])
        self.assertNotEqual(result['status'], 'COMPLETE')

    def test_prediction_keeps_g2_repair_used(self):
        api = Mock(side_effect=[envelope(draft()), envelope(judge(False)), envelope(draft()), envelope(judge())])
        items = [self.two_items()[0]]
        _result, _saved, rows, pipelines = self.saved_batch('G2', api, items)
        self.assertTrue(pipelines[0]['repair_used'])
        self.assertTrue(rows[0]['repair_used'])
        self.assertEqual(rows[0]['repair_used'], pipelines[0]['repair_used'])

    def test_error_batch_exits_nonzero(self):
        with patch('scripts.m6_evaluation.protocol_driver.run_saved_protocol',
                   return_value={'protocol': 'G1', 'status': 'COMPLETED_WITH_ERRORS', 'api_requests': 1}):
            code = main(['--protocol', 'G1',
                         '--retrieval-run', str(ROOT / 'm5_runs/d_dev_retrieval/C_hybrid_k5_skip'),
                         '--output-dir', 'new-dir', '--generate'])
        self.assertEqual(code, 1)


if __name__ == '__main__':
    unittest.main()
