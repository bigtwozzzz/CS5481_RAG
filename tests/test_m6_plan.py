"""Offline checks for the M6 plan. No model and no paid API."""
import json
import unittest
from pathlib import Path

from scripts.m6_evaluation.check_experiment_plan import (
    check_manifest, check_plan, file_sha256, load_json, observed_protocol, protocol_problems)

ROOT = Path(__file__).resolve().parents[1]


def pipeline(status='ANSWERED', gate='AUTOMATIC_REVIEW_PASSED', stages=(), reviews=False, repair=False):
    return {
        'status': status,
        'gate': gate,
        'repair_used': repair,
        'api_calls': [{'stage': stage} for stage in stages],
        'attempts': [{'review': {'decision': 'PASS'} if reviews else None}],
    }


class PlanTests(unittest.TestCase):
    def test_draft_plan_and_template_stay_unfrozen(self):
        plan = load_json(ROOT / 'configs/m6/experiment_plan_draft.json')
        manifest = load_json(ROOT / 'configs/m6/run_manifest.template.json')
        self.assertEqual(check_plan(plan, ROOT), [])
        self.assertEqual(check_manifest(manifest, plan), [])
        plan['freeze_status'] = 'frozen'
        self.assertIn('draft plan is not a freeze record', check_plan(plan, ROOT))

    def test_holdout_and_zero_cost_stay_blocked(self):
        plan = load_json(ROOT / 'configs/m6/experiment_plan_draft.json')
        manifest = load_json(ROOT / 'configs/m6/run_manifest.template.json')
        manifest['split'] = 'holdout'
        self.assertIn('holdout waits for a freeze record', check_manifest(manifest, plan))
        manifest['freeze_status'] = 'frozen'
        manifest['total_cost'] = 0
        problems = check_manifest(manifest, plan)
        self.assertIn('unknown cost stays null', problems)
        self.assertTrue(any(item.startswith('frozen manifest needs ') for item in problems))
        manifest['freeze_status'] = 'not_frozen'
        manifest['total_cost'] = 0
        self.assertIn('unknown cost stays null', check_manifest(manifest, plan, ROOT))
        manifest['freeze_status'] = 'frozen'
        manifest['total_cost'] = '0'
        self.assertIn('unknown cost stays null', check_manifest(manifest, plan, ROOT))

    def test_frozen_record_and_protocol_rules_are_checked_against_files(self):
        plan = load_json(ROOT / 'configs/m6/experiment_plan_draft.json')
        plan['data']['questions_sha256'] = '0' * 64
        self.assertTrue(any('questions' in item for item in check_plan(plan, ROOT)))
        plan = load_json(ROOT / 'configs/m6/experiment_plan_draft.json')
        plan['driver_rules']['same_evidence'] = False
        self.assertIn('same_evidence', check_plan(plan, ROOT))
        plan = load_json(ROOT / 'configs/m6/experiment_plan_draft.json')
        plan['protocols']['G1']['automatic_review'] = True
        self.assertIn('G1 stops after hard validation', check_plan(plan, ROOT))
        manifest = load_json(ROOT / 'configs/m6/run_manifest.template.json')
        manifest.update(freeze_status='frozen', split='dev', git_commit='a' * 40, working_tree_dirty=True,
                        model='fake', budget_profile='configs/missing.json', budget_profile_sha256='b' * 64,
                        retrieval_run='m5_runs/missing', results_sha256='c' * 64, total_cost=None)
        problems = check_manifest(manifest, plan, ROOT)
        self.assertIn('frozen record needs a clean working tree', problems)
        self.assertIn('frozen commit is not in this repository', problems)
        priced = load_json(ROOT / 'configs/m6/run_manifest.template.json')
        priced.update(total_cost=0, pricing_sha256='ab' * 32, model='deepseek-flash')
        self.assertIn('pricing file does not match its hash', check_manifest(priced, plan, ROOT))
        template = ROOT / 'configs/m5_pricing.template.json'
        priced.update(pricing_file='configs/m5_pricing.template.json', pricing_sha256=file_sha256(template),
                      freeze_status='not_frozen')
        self.assertIn('pricing rates are not valid for the manifest model', check_manifest(priced, plan, ROOT))
        claimed = load_json(ROOT / 'configs/m6/run_manifest.template.json')
        claimed.update(freeze_status='frozen', working_tree_dirty=False, split='dev',
                       git_commit='fa2fc97637bf5fbd41a8f3f9aefac6ad1dfb74eb', model='deepseek-flash',
                       budget_profile='configs/m5_budget_cityu_cs5351.json',
                       budget_profile_sha256=file_sha256(ROOT / 'configs/m5_budget_cityu_cs5351.json'),
                       questions_file='data/evaluation/inputs/m5_dev.questions.jsonl',
                       questions_sha256=file_sha256(ROOT / 'data/evaluation/inputs/m5_dev.questions.jsonl'),
                       gold_file='data/evaluation/m5_dev.json',
                       gold_sha256=file_sha256(ROOT / 'data/evaluation/m5_dev.json'),
                       retrieval_run='m5_runs/missing', results_sha256='c' * 64, total_cost=None)
        claimed_problems = check_manifest(claimed, plan, ROOT)
        self.assertIn('frozen record needs a clean working tree', claimed_problems)
        self.assertIn('frozen budget is not in the commit', claimed_problems)
        self.assertTrue(any(item.startswith('frozen budget:') for item in problems))
        self.assertTrue(any('evidence results are not bound' in item for item in problems))

    def test_review_is_g2_and_shortcuts_are_rejected(self):
        reviewed = pipeline(stages=('generation', 'review'), reviews=True, repair=False)
        repaired = pipeline(stages=('generation', 'review', 'repair_generation', 'repair_review'), reviews=True, repair=True)
        dry = pipeline(status='READY_FOR_PIPELINE', gate='NOT_RUN')
        generated = pipeline(stages=('generation',), reviews=False, gate='NOT_EVALUATED')
        self.assertEqual(observed_protocol(reviewed), 'G2')
        self.assertEqual(protocol_problems('G2', repaired), [])
        self.assertTrue(protocol_problems('G1', reviewed))
        self.assertEqual(observed_protocol(dry), 'not_a_protocol')
        self.assertTrue(protocol_problems('G0', dry))
        self.assertEqual(observed_protocol(generated), 'unreviewed_generation')
        self.assertTrue(protocol_problems('G1', generated))
        stripped = json.loads(json.dumps(repaired))
        for call in stripped['api_calls']:
            if call['stage'] in {'review', 'repair_review'}:
                call['stage'] = 'generation'
        for attempt in stripped['attempts']:
            attempt['review'] = None
        self.assertTrue(protocol_problems('G1', stripped))

    def test_saved_smoke_pipeline_is_g2(self):
        path = ROOT / 'm5_runs/b_2db23a0069f644b0b69afa5728db6ce3/item_0001/pipeline.json'
        saved = load_json(path)
        self.assertEqual(protocol_problems('G2', saved), [])
        self.assertTrue(protocol_problems('G0', saved))
        self.assertTrue(protocol_problems('G1', saved))


if __name__ == '__main__':
    unittest.main()
