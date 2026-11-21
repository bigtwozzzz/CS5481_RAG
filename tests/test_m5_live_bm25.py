"""Real M4 BM25/RRF and packing regressions over a small in-memory corpus.

Only embedding vectors and the collection backend are fixtures. Retrieval, BM25,
RRF, schema validation and packing execute the production implementations.
"""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.m4_retrieval import workshop_checks as fixtures
from scripts.m5_live.retrieval_worker import retrieve_packed
from scripts.m5_generation.m4_input import prepare_input

ROOT=Path(__file__).resolve().parents[1]


class LiveBM25Tests(unittest.TestCase):
    def workshop(self):
        fixture=fixtures.WorkshopTests()
        fixture.schema=json.loads((ROOT/'schemas/retrieval_response.v2.schema.json').read_text(encoding='utf-8'))
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        w=fixture.w
        raw=fixture.collection.raw
        w.rows={s:[{'chunk_id':raw['ids'][0][0], 'text':raw['documents'][0][0],
                    'meta':deepcopy(raw['metadatas'][0][0])}] for s in 'ABC'}
        return w

    def config(self,mode='hybrid',strategy='C'):
        return {'mode':mode,'strategy':strategy,'top_k':5,'candidate_k':30,'rrf_constant':60,'context_tokens':1024}

    def test_reproduces_uninitialized_worker_failure(self):
        w=self.workshop()
        result=w.retrieve('news',strategy='C',mode='hybrid',top_k=5,candidate_k=30,rrf_constant=60)
        self.assertEqual(result['status'],'ERROR')
        self.assertEqual(result['error']['code'],'BM25_NOT_READY')
        self.assertEqual(w.lexical,{})

    def test_fresh_hybrid_worker_builds_index_and_packs_evidence(self):
        for strategy in 'ABC':
            with self.subTest(strategy=strategy):
                w=self.workshop()
                packed=retrieve_packed(w,'news',self.config(strategy=strategy))
                self.assertEqual(packed['retrieval']['status'],'OK')
                row=packed['retrieval']['results'][0]
                self.assertEqual(row['retrieved_by'],['dense','bm25'])
                self.assertGreater(row['scores']['bm25'],0)
                self.assertAlmostEqual(row['scores']['rrf'],2/61)
                self.assertEqual(packed['selected_chunk_ids'],[row['chunk_id']])
                self.assertGreater(packed['context_tokens'],0)
                prepare_input(packed)

    def test_fresh_bm25_workers_for_all_strategies(self):
        for strategy in 'ABC':
            with self.subTest(strategy=strategy):
                w=self.workshop()
                packed=retrieve_packed(w,'news',self.config('bm25',strategy))
                self.assertEqual(packed['retrieval']['status'],'OK')
                self.assertEqual(packed['retrieval']['results'][0]['retrieved_by'],['bm25'])
                self.assertIsNone(packed['retrieval']['results'][0]['scores']['distance'])
                prepare_input(packed)

    def test_dense_does_not_build_bm25(self):
        w=self.workshop()
        with patch.object(w,'build_bm25',side_effect=AssertionError('Dense must not build lexical indices')):
            packed=retrieve_packed(w,'news',self.config('dense'))
        self.assertEqual(packed['retrieval']['status'],'OK')
        self.assertEqual(w.lexical,{})

    def test_repeated_retrieval_reuses_existing_bm25_objects(self):
        w=self.workshop()
        first=retrieve_packed(w,'news',self.config())
        indices=dict(w.lexical)
        second=retrieve_packed(w,'news',self.config())
        self.assertEqual(first['selected_chunk_ids'],second['selected_chunk_ids'])
        for s in 'ABC':self.assertIs(indices[s],w.lexical[s])

    def test_index_build_failure_stops_before_retrieval(self):
        w=self.workshop()
        with patch.object(w,'build_bm25',side_effect=RuntimeError('Simulated index-build failure')), \
             patch.object(w,'retrieve') as retrieve:
            with self.assertRaisesRegex(RuntimeError,'index-build failure'):
                retrieve_packed(w,'news',self.config())
            retrieve.assert_not_called()

    def test_no_lexical_match_remains_no_evidence(self):
        packed=retrieve_packed(self.workshop(),'unmatchedword',self.config('bm25'))
        self.assertEqual(packed['retrieval']['status'],'NO_EVIDENCE')
        self.assertEqual(packed['selected_chunk_ids'],[])
        self.assertEqual(packed['context'],'')
        prepare_input(packed)


if __name__=='__main__':unittest.main()
