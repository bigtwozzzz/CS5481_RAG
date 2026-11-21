"""A adapter offline acceptance: real schema/budget checks; fixture retrieval."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock

from scripts.m4_retrieval.cli import load_requests, run_batch, validate_config, error_response
from scripts.m4_retrieval.packing import pack_response, render_block
from scripts.m4_retrieval.workshop import Workshop
from scripts.m5_generation.api import M5Error
from scripts.m5_generation.generator import generate_answer
from scripts.m5_generation.m4_input import prepare_input

ROOT=Path(__file__).resolve().parents[1]


def tokenizer(text, **kwargs):
    assert kwargs == {'truncation':False,'add_special_tokens':False,'verbose':False}
    return {'input_ids':text.split()}


def config():
    return json.loads((ROOT/'configs/m4_m5.yaml').read_text(encoding='utf-8'))


def response(texts=('first evidence','middle '*1000,'last evidence')):
    data=json.loads((ROOT/'documents/m4/m5_hybrid_C_example.json').read_text(encoding='utf-8'))['retrieval']
    data['config']['top_k']=max(len(texts),1)
    data['config']['candidate_k']=max(len(texts),30)
    first=deepcopy(data['results'][0])
    data['results']=[]
    for i,text in enumerate(texts):
        row=deepcopy(first)
        row.update(rank=i+1,chunk_index=i,chunk_id=hashlib.sha256(('fixture'+str(i)).encode()).hexdigest(),
                   text=text,text_sha256=hashlib.sha256(text.encode()).hexdigest())
        data['results'].append(row)
    return data


class PackingTests(unittest.TestCase):
    def test_skip_fits_later_block_and_legacy_matches_workshop(self):
        data=response(); original=deepcopy(data)
        budget=len((render_block(data['results'][0])+render_block(data['results'][2])).split())
        new,audit=pack_response(data,tokenizer,budget,'skip_continue_dedup_v1')
        old,_=pack_response(data,tokenizer,budget,'legacy_break_v1')
        selected,context,used=Workshop.pack(SimpleNamespace(model=SimpleNamespace(tokenizer=tokenizer)),data['results'],budget)
        self.assertEqual(old['context'],context); self.assertEqual(old['context_tokens'],used)
        self.assertEqual(old['selected_chunk_ids'],[x['chunk_id'] for x in selected])
        self.assertEqual(new['selected_chunk_ids'],[data['results'][i]['chunk_id'] for i in (0,2)])
        self.assertEqual(audit['excluded'][0]['reason'],'context_token_budget')
        self.assertEqual(data,original); prepare_input(new)

    def test_first_oversized_chunk_does_not_hide_later_evidence(self):
        data=response(('huge '*1000,'small'))
        packed,_=pack_response(data,tokenizer,100,'skip_continue_dedup_v1')
        self.assertEqual(packed['selected_chunk_ids'],[data['results'][1]['chunk_id']])

    def test_identical_text_same_source_deduplicated(self):
        data=response(('same','same'))
        packed,audit=pack_response(data,tokenizer,1000,'skip_continue_dedup_v1')
        self.assertEqual(len(packed['selected_chunk_ids']),1)
        self.assertEqual(audit['excluded'][0]['reason'],'duplicate_text_same_source')

    def test_independent_source_text_preserved(self):
        data=response(('same','same')); data['results'][1]['document_id']='another-document'
        packed,_=pack_response(data,tokenizer,1000,'skip_continue_dedup_v1')
        self.assertEqual(len(packed['selected_chunk_ids']),2)

    def test_source_metadata_conflict_preserved_and_reported(self):
        data=response(('same','same')); data['results'][1]['citation']['title']='Another title'
        packed,audit=pack_response(data,tokenizer,1000,'skip_continue_dedup_v1')
        self.assertEqual(len(packed['selected_chunk_ids']),2)
        self.assertEqual(audit['source_metadata_conflicts'][0]['kind'],'SOURCE_METADATA_CONFLICT')
        self.assertEqual(audit['semantic_conflict_check'],'not_performed')

    def test_duplicate_identity_rejected(self):
        data=response(('one','two')); data['results'][1]['chunk_id']=data['results'][0]['chunk_id']
        with self.assertRaises(M5Error):pack_response(data,tokenizer)

    def test_offsets_recover_exact_unicode_text(self):
        data=response(('English \u4e2d\u6587 \U0001f680\nsecond line','another paragraph'))
        packed,audit=pack_response(data,tokenizer,1000,'skip_continue_dedup_v1')
        self.assertEqual([r['source_id'] for r in audit['source_mapping']],['S1','S2'])
        for row,mapping in zip(data['results'],audit['source_mapping']):
            self.assertEqual(packed['context'][mapping['context_text_start']:mapping['context_text_end']],row['text'])
            self.assertEqual(row['text'][mapping['chunk_text_start']:mapping['chunk_text_end']],row['text'])

    def test_exact_boundary_and_one_under(self):
        data=response(('small',)); required=len(render_block(data['results'][0]).split())
        self.assertEqual(pack_response(data,tokenizer,required)[0]['context_tokens'],required)
        packed,audit=pack_response(data,tokenizer,required-1,'skip_continue_dedup_v1')
        self.assertEqual(packed['retrieval']['status'],'OK')
        self.assertEqual(audit['selection_status'],'EMPTY_SELECTED_CONTEXT')
        result=generate_answer(packed,dry_run=True)
        self.assertEqual(result['error']['code'],'EMPTY_SELECTED_CONTEXT')

    def test_empty_and_error_do_not_invoke_tokenizer(self):
        data=response(('small',));data.update(status='NO_EVIDENCE',results=[])
        no_calls=Mock(side_effect=AssertionError('No tokenizer needed'))
        for value in (data,error_response('RETRIEVAL_TIMEOUT','Fixture timeout')):
            packed,_=pack_response(value,no_calls)
            self.assertEqual(packed['context_tokens'],0); self.assertEqual(packed['context'],'')
            prepare_input(packed)
        no_calls.assert_not_called()

    def test_invalid_budget_or_policy(self):
        for budget in (True,0,-1,8193):
            with self.assertRaises(M5Error):pack_response(response(),tokenizer,budget)
        with self.assertRaises(M5Error):pack_response(response(),tokenizer,100,'unknown')

    def test_m5_real_tokenizer_preflight_uses_only_selected_evidence(self):
        data=response(); packed,_=pack_response(data,tokenizer,100,'skip_continue_dedup_v1')
        api=Mock(side_effect=AssertionError('No API calls'))
        key=Mock(side_effect=AssertionError('No key access'))
        result=generate_answer(packed,dry_run=True,api_call=api,key_provider=key)
        self.assertEqual(result['status'],'READY_FOR_GENERATION')
        self.assertEqual([r['chunk_id'] for r in result['evidence']],packed['selected_chunk_ids'])
        self.assertEqual(result['token_budget']['check_status'],'PASS')
        self.assertFalse(result['token_budget']['provider_tokenizer_parity_verified'])
        api.assert_not_called(); key.assert_not_called()


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)

    def requests(self, lines):
        path=self.base/'input.jsonl'
        path.write_text('\n'.join(json.dumps(line) if not isinstance(line,str) else line for line in lines),encoding='utf-8')
        return load_requests(path)

    def workshop(self,fail=False):
        def retrieve(question,**kwargs):
            if fail:raise RuntimeError('fixture failure')
            data=response(('news evidence',));data['query']=data['retrieval_query']=question
            return data
        return SimpleNamespace(model=SimpleNamespace(tokenizer=tokenizer),build_bm25=Mock(),retrieve=Mock(side_effect=retrieve))

    def test_malformed_line_does_not_discard_good_rows(self):
        items=self.requests([{'id':'one','question':'first'},'{bad',{'id':'two','question':'last'}])
        self.assertIsNone(items[0]['error']);self.assertIsNotNone(items[1]['error']);self.assertIsNone(items[2]['error'])
        self.assertEqual([r['line'] for r in items],[1,2,3])

    def test_unknown_gold_fields_rejected(self):
        items=self.requests([{'id':'gold','question':'q','reference_answer':'must not enter retrieval'}])
        self.assertEqual(items[0]['error']['code'],'UNSUPPORTED_REQUEST_FIELDS')
        self.assertNotIn('must not enter retrieval',json.dumps(items))

    def test_duplicate_id_rejected(self):
        items=self.requests([{'id':'x','question':'q'},{'id':'x','question':'r'}])
        self.assertEqual(items[1]['error']['code'],'DUPLICATE_ID')

    def test_empty_query_rejected(self):
        self.assertEqual(self.requests([{'id':'x','question':'  '}])[0]['error']['code'],'EMPTY_QUERY')

    def test_date_and_other_filters_are_explicit_errors(self):
        items=self.requests([{'id':'d','question':'q','filters':{'date_from_ts':0}},
            {'id':'s','question':'q','filters':{'section':'world'}}])
        self.assertEqual([r['error']['code'] for r in items],['UNSUPPORTED_DATE_FILTER','UNSUPPORTED_FILTER'])

    def test_check_only_never_loads_model(self):
        factory=Mock(side_effect=AssertionError('No startup'))
        result=run_batch(self.requests([{'id':'one','question':'q'}]),config(),self.base/'run',factory,True)
        self.assertEqual(result['status_counts'],{'READY_FOR_RETRIEVAL':1})
        self.assertFalse(result['generation_budget_verified']);factory.assert_not_called()

    def test_live_batch_reuses_model_and_keeps_invalid_row(self):
        items=self.requests([{'id':'one','question':'first'},'{bad',{'id':'two','question':'second'}])
        factory=Mock(return_value=self.workshop()); out=self.base/'run'
        result=run_batch(items,config(),out,factory)
        factory.assert_called_once()
        self.assertEqual(result['status_counts'],{'OK':2,'ERROR':1})
        records=[json.loads(line) for line in (out/'results.jsonl').read_text().splitlines()]
        for record in records:prepare_input(json.loads((out/record['packed_file']).read_text()))
        self.assertFalse(records[1]['live_retrieval_executed'])
        self.assertEqual(records[1]['error']['code'],'INVALID_JSON')

    def test_startup_failure_is_not_retried_or_refusal(self):
        factory=Mock(side_effect=RuntimeError('fixture startup'))
        result=run_batch(self.requests([{'id':'a','question':'q'},{'id':'b','question':'r'}]),config(),self.base/'run',factory)
        factory.assert_called_once();self.assertEqual(result['status_counts'],{'ERROR':2})

    def test_retrieval_exception_is_error(self):
        out=self.base/'run'
        result=run_batch(self.requests([{'id':'a','question':'q'}]),config(),out,lambda:self.workshop(True))
        self.assertEqual(result['status_counts'],{'ERROR':1})
        item=json.loads((out/'results.jsonl').read_text())
        self.assertEqual(item['error']['code'],'RETRIEVAL_FAILED')

    def test_upstream_timeout_code_is_preserved(self):
        w=self.workshop();w.retrieve=Mock(return_value=error_response('RETRIEVAL_TIMEOUT','Fixture timeout','q'))
        out=self.base/'run'
        run_batch(self.requests([{'id':'a','question':'q'}]),config(),out,lambda:w)
        self.assertEqual(json.loads((out/'results.jsonl').read_text())['error']['code'],'RETRIEVAL_TIMEOUT')

    def test_no_evidence_is_distinct_from_error(self):
        w=self.workshop();data=response(('x',));data.update(query='q',retrieval_query='q',status='NO_EVIDENCE',results=[])
        w.retrieve=Mock(return_value=data)
        result=run_batch(self.requests([{'id':'a','question':'q'}]),config(),self.base/'run',lambda:w)
        self.assertEqual(result['status_counts'],{'NO_EVIDENCE':1})

    def test_interrupt_leaves_incomplete_manifest(self):
        w=self.workshop();w.retrieve=Mock(side_effect=KeyboardInterrupt())
        out=self.base/'run'
        with self.assertRaises(KeyboardInterrupt):
            run_batch(self.requests([{'id':'a','question':'q'}]),config(),out,lambda:w)
        self.assertEqual(json.loads((out/'run.json').read_text())['status'],'INTERRUPTED')

    def test_no_overwrite_of_prior_directory(self):
        out=self.base/'run';out.mkdir();(out/'sentinel').write_text('keep')
        with self.assertRaises(FileExistsError):run_batch([],config(),out,check_only=True)
        self.assertEqual((out/'sentinel').read_text(),'keep')

    def test_config_rejects_bool_and_unknown_keys(self):
        for data in ({**config(),'top_k':True},{**config(),'gold':'forbidden'},{**config(),'top_k':31}):
            with self.assertRaises(M5Error):validate_config(data)


if __name__=='__main__':unittest.main()
