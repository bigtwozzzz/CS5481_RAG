"""Offline checks for the summary script. No model and no paid API."""
import json
import tempfile
import unittest
from pathlib import Path

from scripts.m6_evaluation.summarize_run import file_sha256, percentile, summarize_generation, summarize_scores


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


class SummaryTests(unittest.TestCase):
    def test_percentiles(self):
        self.assertEqual(percentile([10, 20, 30, 40], 0.50), 25.0)
        self.assertEqual(percentile([10, 20, 30, 40], 0.95), 38.5)

    def test_error_stays_in_denominator_and_calibration_stays_out(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'scores.csv'
            path.write_text(
                'case_role,run_id,id,split,event_id,answerable,protocol,system_status,system_failure,'
                'explicit_refusal,invented_missing_slot,mixed_unanswerable_slot,required_fact_ids,fact_marks,'
                'citation_support,fact_citation_marks,irrelevant_fact_count,primary_label,partial_reason,refusal_label,reviewer,'
                'disputed,adjudicator,adjudication,notes,eligible\n'
                'pending,run,m5_dev_011,dev,event_aircon,true,G2,ANSWERED,NO,NO,NO,NO,m5_dev_011_f1,'
                'm5_dev_011_f1=PRESENT,FULL,m5_dev_011_f1=CITED,0,CORRECT,,NOT_APPLICABLE,tester,NO,,,example,fill_after_generation\n'
                'pending,run,m5_dev_003,dev,event_astronaut,false,G2,ERROR,YES,NO,NO,NO,,'
                ',NOT_APPLICABLE,,0,ERROR,,NOT_APPLICABLE,tester,NO,,,failed,fill_after_generation\n',
                encoding='utf-8')
            summary = summarize_scores(path)
            calibration = summarize_scores(root / 'data/evaluation/scoring_calibration_v1.csv')
        self.assertEqual(summary['labels_all_requests']['CORRECT']['text'], '1/2')
        self.assertEqual(summary['labels_excluding_error']['CORRECT']['text'], '1/1')
        self.assertEqual(summary['error_requests_retained']['text'], '1/2')
        self.assertEqual(summary['fact_coverage_excluding_error']['text'], '1/1')
        self.assertEqual(summary['citation_coverage_excluding_error']['text'], '1/1')
        self.assertEqual(calibration['official_rows'], 0)

    def test_missing_cost_remains_unknown_and_error_request_is_counted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write(root / 'run.json', {'status': 'COMPLETED_WITH_ERRORS', 'request_count': 1, 'api_requests': 1,
                                      'billing': {'total_cost': None, 'reason': 'pricing_not_configured',
                                                  'missing_or_unknown_calls': [1]}})
            pipeline = root / 'item_0001' / 'pipeline.json'
            write(pipeline, {'status': 'ERROR', 'request_id': 'r1', 'repair_used': False, 'api_calls': [
                {'stage': 'generation', 'state': 'ERROR', 'input_tokens': None, 'output_tokens': None,
                 'latency_ms': 12, 'error_code': 'HTTP_401'}]})
            (root / 'predictions.jsonl').write_text(json.dumps({
                'id': 'q', 'status': 'ERROR', 'request_id': 'r1', 'pipeline_file': 'item_0001/pipeline.json',
                'pipeline_sha256': file_sha256(pipeline)}) + '\n', encoding='utf-8')
            summary = summarize_generation(root)
        self.assertIsNone(summary['total_cost'])
        self.assertFalse(summary['cost_known'])
        self.assertIsNone(summary['tokens']['input_tokens'])
        self.assertEqual(summary['error_requests']['text'], '1/1')
        self.assertEqual(summary['unfinished_requests']['text'], '0/1')
        self.assertEqual(summary['api_calls'], 1)

    def test_interrupted_batch_keeps_planned_denominator(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write(root / 'run.json', {'status': 'RUNNING', 'request_count': 15, 'api_requests': 1,
                                      'billing': {'total_cost': None}})
            pipeline = root / 'item_0001' / 'pipeline.json'
            write(pipeline, {'status': 'ERROR', 'request_id': 'r1', 'repair_used': False, 'api_calls': [
                {'stage': 'generation', 'state': 'ERROR', 'input_tokens': 4, 'output_tokens': 0, 'latency_ms': 3}]})
            (root / 'predictions.jsonl').write_text(json.dumps({
                'id': 'q1', 'status': 'ERROR', 'request_id': 'r1', 'pipeline_file': 'item_0001/pipeline.json',
                'pipeline_sha256': file_sha256(pipeline)}) + '\n', encoding='utf-8')
            summary = summarize_generation(root)
        self.assertEqual(summary['request_count'], 15)
        self.assertEqual(summary['saved_predictions'], 1)
        self.assertEqual(summary['error_requests']['text'], '1/15')
        self.assertEqual(summary['unfinished_requests']['text'], '14/15')
        self.assertFalse(summary['token_usage_complete'])

    def test_unknown_and_duplicate_ids_stay_out_of_official_scores(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'scores.csv'
            header = (
                'case_role,run_id,id,split,event_id,answerable,protocol,system_status,system_failure,'
                'explicit_refusal,invented_missing_slot,mixed_unanswerable_slot,required_fact_ids,fact_marks,'
                'citation_support,fact_citation_marks,irrelevant_fact_count,primary_label,partial_reason,refusal_label,reviewer,'
                'disputed,adjudicator,adjudication,notes,eligible\n')
            known = (
                'pending,run,m5_dev_011,dev,event_aircon,true,G2,ANSWERED,NO,NO,NO,NO,m5_dev_011_f1,'
                'm5_dev_011_f1=PRESENT,FULL,m5_dev_011_f1=CITED,0,CORRECT,,NOT_APPLICABLE,tester,NO,,,example,fill_after_generation\n')
            unknown = known.replace('m5_dev_011', 'm5_missing')
            path.write_text(header + unknown + known + known, encoding='utf-8')
            summary = summarize_scores(path)
            wrong = Path(folder) / 'wrong_facts.csv'
            wrong.write_text(header + known.replace('m5_dev_011_f1,', 'm5_dev_011_f9,'), encoding='utf-8')
            rejected = summarize_scores(wrong)
        self.assertEqual(summary['official_rows'], 0)
        self.assertEqual(summary['labels_all_requests'], {})
        self.assertIn('unknown id', summary['check_problems'][0]['errors'])
        self.assertIn('duplicate id in the same run', summary['check_problems'][1]['errors'])
        self.assertEqual(rejected['official_rows'], 0)
        self.assertIn('required facts differ from gold', rejected['check_problems'][0]['errors'])

    def test_citation_coverage_counts_cited_present_facts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'scores.csv'
            path.write_text(
                'case_role,run_id,id,split,event_id,answerable,protocol,system_status,system_failure,'
                'explicit_refusal,invented_missing_slot,mixed_unanswerable_slot,required_fact_ids,fact_marks,'
                'citation_support,fact_citation_marks,irrelevant_fact_count,primary_label,partial_reason,'
                'refusal_label,reviewer,disputed,adjudicator,adjudication,notes,eligible\n'
                'pending,run,m5_dev_001,dev,event_astronaut,true,G2,ANSWERED,NO,NO,NO,NO,'
                'm5_dev_001_f1;m5_dev_001_f2,m5_dev_001_f1=PRESENT;m5_dev_001_f2=PRESENT,PARTIAL,'
                'm5_dev_001_f1=CITED;m5_dev_001_f2=UNCITED,0,PARTIAL,CITATION,NOT_APPLICABLE,tester,NO,,,'
                'one citation,fill_after_generation\n',
                encoding='utf-8')
            summary = summarize_scores(path)
        self.assertEqual(summary['check_problems'], [])
        self.assertEqual(summary['citation_coverage_excluding_error']['text'], '1/2')

    def test_pipeline_hash_mismatch_blocks_token_total(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write(root / 'run.json', {'status': 'COMPLETE', 'request_count': 1, 'billing': {'total_cost': None}})
            pipeline = root / 'item_0001' / 'pipeline.json'
            write(pipeline, {'repair_used': False, 'api_calls': [
                {'stage': 'generation', 'state': 'RECEIVED', 'input_tokens': 10, 'output_tokens': 1, 'latency_ms': 5}]})
            recorded = file_sha256(pipeline)
            pipeline.write_text(pipeline.read_text(encoding='utf-8').replace('10', '9999'), encoding='utf-8')
            (root / 'predictions.jsonl').write_text(json.dumps({
                'id': 'q', 'status': 'ANSWERED', 'pipeline_file': 'item_0001/pipeline.json',
                'pipeline_sha256': recorded}) + '\n', encoding='utf-8')
            summary = summarize_generation(root)
        self.assertFalse(summary['ledger_verified'])
        self.assertIsNone(summary['tokens']['input_tokens'])
        self.assertIsNone(summary['api_calls'])

    def test_unlinked_checkpoint_keeps_call_total_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write(root / 'run.json', {'status': 'INTERRUPTED', 'request_count': 2, 'api_requests': None,
                                      'billing': {'total_cost': None}})
            first = root / 'item_0001' / 'pipeline.json'
            write(first, {'request_id': 'r1', 'repair_used': False, 'api_calls': [
                {'stage': 'generation', 'state': 'RECEIVED', 'input_tokens': 10, 'output_tokens': 1, 'latency_ms': 4}]})
            write(root / 'item_0002' / 'pipeline.json', {'request_id': 'r2', 'repair_used': False, 'api_calls': [
                {'stage': 'generation', 'state': 'RECEIVED', 'input_tokens': 7, 'output_tokens': 1, 'latency_ms': 4}]})
            (root / 'predictions.jsonl').write_text(json.dumps({
                'id': 'q1', 'status': 'ANSWERED', 'request_id': 'r1', 'pipeline_file': 'item_0001/pipeline.json',
                'pipeline_sha256': file_sha256(first)}) + '\n', encoding='utf-8')
            summary = summarize_generation(root)
        self.assertFalse(summary['ledger_verified'])
        self.assertIsNone(summary['api_calls'])
        self.assertIsNone(summary['tokens']['input_tokens'])
        self.assertEqual(summary['verified_subtotal']['api_calls'], 1)
        self.assertEqual(summary['verified_subtotal']['tokens']['input_tokens'], 10)
        self.assertEqual(summary['unfinished_requests']['text'], '1/2')

    def test_reused_pipeline_and_request_id_do_not_double_count(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write(root / 'run.json', {'status': 'COMPLETE', 'request_count': 2, 'api_requests': 1,
                                      'billing': {'total_cost': None}})
            pipeline = root / 'item_0001' / 'pipeline.json'
            write(pipeline, {'request_id': 'r1', 'repair_used': False, 'api_calls': [
                {'stage': 'generation', 'state': 'RECEIVED', 'input_tokens': 10, 'output_tokens': 1, 'latency_ms': 4}]})
            row = {'status': 'ANSWERED', 'request_id': 'r1', 'pipeline_file': 'item_0001/pipeline.json',
                   'pipeline_sha256': file_sha256(pipeline)}
            lines = [dict(row, id='q1'), dict(row, id='q2')]
            (root / 'predictions.jsonl').write_text(''.join(json.dumps(item) + '\n' for item in lines), encoding='utf-8')
            reused = summarize_generation(root)
            (root / 'predictions.jsonl').write_text(json.dumps(dict(row, id='q1', request_id='other')) + '\n', encoding='utf-8')
            mismatched = summarize_generation(Path(folder))
        self.assertFalse(reused['ledger_verified'])
        self.assertIsNone(reused['api_calls'])
        self.assertIsNone(reused['tokens']['input_tokens'])
        self.assertIsNone(reused['verified_subtotal'])
        self.assertFalse(reused['token_usage_complete'])
        self.assertFalse(mismatched['ledger_verified'])
        self.assertIn('request id mismatch', mismatched['ledger_problems'][0]['errors'])

    def test_unknown_manifest_calls_block_a_complete_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write(root / 'run.json', {'status': 'COMPLETE', 'request_count': 1, 'api_requests': None,
                                      'billing': {'total_cost': None}})
            pipeline = root / 'item_0001' / 'pipeline.json'
            write(pipeline, {'request_id': 'r1', 'repair_used': False, 'api_calls': [
                {'stage': 'generation', 'state': 'RECEIVED', 'input_tokens': 10, 'output_tokens': 1, 'latency_ms': 4}]})
            (root / 'predictions.jsonl').write_text(json.dumps({
                'id': 'q1', 'status': 'ANSWERED', 'request_id': 'r1', 'pipeline_file': 'item_0001/pipeline.json',
                'pipeline_sha256': file_sha256(pipeline)}) + '\n', encoding='utf-8')
            summary = summarize_generation(root)
        self.assertEqual(summary['unfinished_requests']['text'], '0/1')
        self.assertFalse(summary['ledger_verified'])
        self.assertIsNone(summary['api_calls'])
        self.assertIsNone(summary['tokens']['input_tokens'])
        self.assertEqual(summary['verified_subtotal']['api_calls'], 1)
        self.assertEqual(summary['verified_subtotal']['tokens']['input_tokens'], 10)

    def test_equivalent_pipeline_paths_are_not_counted_twice(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write(root / 'run.json', {'status': 'COMPLETE', 'request_count': 2, 'api_requests': 2,
                                      'billing': {'total_cost': None}})
            pipeline = root / 'item_0001' / 'pipeline.json'
            write(pipeline, {'request_id': 'r1', 'repair_used': False, 'api_calls': [
                {'stage': 'generation', 'state': 'RECEIVED', 'input_tokens': 10, 'output_tokens': 1, 'latency_ms': 4}]})
            digest = file_sha256(pipeline)
            rows = [
                {'id': 'q1', 'status': 'ANSWERED', 'request_id': 'r1', 'pipeline_file': 'item_0001/pipeline.json',
                 'pipeline_sha256': digest},
                {'id': 'q2', 'status': 'ANSWERED', 'request_id': 'r1', 'pipeline_file': 'item_0001/./pipeline.json',
                 'pipeline_sha256': digest},
            ]
            (root / 'predictions.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
            summary = summarize_generation(root)
        self.assertFalse(summary['ledger_verified'])
        self.assertIsNone(summary['api_calls'])
        self.assertIsNone(summary['tokens']['input_tokens'])
        self.assertFalse(summary['token_usage_complete'])
        self.assertIn('duplicate pipeline path', summary['ledger_problems'][0]['errors'])


if __name__ == '__main__':
    unittest.main()
