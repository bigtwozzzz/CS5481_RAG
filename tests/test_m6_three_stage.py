"""Offline checks for three-stage retrieval scoring. No retrieval and no paid API."""
import unittest

from scripts.m6_evaluation.score_three_stage_evidence import (
    chunk_covers, newly_dropped, recorded_inputs, score_list, sha256_file, ROOT, PROMPTS, GOLD,
)


class ThreeStageScoreTests(unittest.TestCase):
    def test_same_text_in_another_document_is_not_a_hit(self):
        units = [{'quote': 'same words', 'document_id': 'doc-a', 'evidence_id': 'e1'}]
        texts = {'c1': 'prefix same words suffix', 'c2': 'prefix same words suffix'}
        docs = {'c1': 'doc-b', 'c2': 'doc-a'}
        self.assertFalse(chunk_covers('c1', units[0], texts, docs))
        self.assertTrue(chunk_covers('c2', units[0], texts, docs))
        wrong = score_list(['c1'], ['doc-b'], units, texts, docs)
        right = score_list(['c1', 'c2'], ['doc-b', 'doc-a'], units, texts, docs)
        self.assertEqual(wrong['hit'], 0)
        self.assertEqual(wrong['complete'], 0)
        self.assertEqual(wrong['rr'], 0.0)
        self.assertEqual(right['hit'], 1)
        self.assertEqual(right['rr'], 0.5)

    def test_budget_drop_keeps_questions_already_incomplete(self):
        raw = [{'id': 'm5_dev_002', 'complete': 0}, {'id': 'm5_dev_009', 'complete': 1}]
        packed = [{'id': 'm5_dev_002', 'complete': 0}, {'id': 'm5_dev_009', 'complete': 0}]
        self.assertEqual(newly_dropped(raw, packed), ['m5_dev_009'])

    def test_recorded_inputs_hash_gold_prompts_and_builtin_budget(self):
        recorded = recorded_inputs()
        self.assertEqual(recorded['gold_sha256'], sha256_file(GOLD))
        self.assertEqual(set(recorded['prompt_sha256']), set(PROMPTS))
        for relative, digest in recorded['prompt_sha256'].items():
            self.assertEqual(digest, sha256_file(ROOT / relative))
        budget = recorded['m5_input_budget']
        self.assertEqual(budget['model'], 'deepseek-flash')
        self.assertEqual(budget['profile_version'], 'm5-token-budget-v0.5')
        self.assertEqual(len(budget['profile_sha256']), 64)
        self.assertEqual(recorded['m4_context_tokens'], 1024)


if __name__ == '__main__':
    unittest.main()
