"""Offline B acceptance: fake HTTP/model responses are not quality evaluation."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from scripts.m5_generation.api import M5Error,read_key
from scripts.m5_generation.pipeline import run_pipeline
from scripts.m5_generation.billing import summarize_calls,validate_pricing
from scripts.m5_generation.batch import run_saved_batch,load_a_run
from scripts.m5_generation.public_contracts import export_pipeline_contracts
from scripts.m4_retrieval.cli import run_batch,load_requests
from scripts.m5_live.common import sha_file,write_json
from test_m5_pipeline import fixture,draft,judge,envelope
import test_m5_a_adapter as a_helpers


def prices():
    return {'schema_version':'m5_pricing.v1','model':'deepseek-flash','currency':'USD',
            'input_cache_hit_per_million':'1','input_cache_miss_per_million':'2','output_per_million':'3',
            'source_url':'https://example.com/SYNTHETIC_TEST_PRICES','verified_at_utc':'2026-11-21T00:00:00Z'}


def response(content):
    value=envelope(content);value['model']='deepseek-flash'
    value['usage'].update(prompt_cache_hit_tokens=40,prompt_cache_miss_tokens=60)
    return value


class KeyAndRetryTests(unittest.TestCase):
    def call(self,values,**kwargs):
        api=Mock(side_effect=values);sleep=Mock();key=Mock(return_value='SECRET_TEST_ONLY')
        state=run_pipeline(fixture(),api_call=api,key_provider=key,retry_sleep=sleep,**kwargs)
        self.assertNotIn('SECRET_TEST_ONLY',json.dumps(state))
        return state,api,sleep

    def test_missing_key_never_prompts_or_calls(self):
        with patch.dict(os.environ,{},clear=True):
            api=Mock()
            result=run_pipeline(fixture(),api_call=api)
            self.assertEqual(result['error']['code'],'MISSING_API_KEY');api.assert_not_called()

    def test_environment_key_and_invalid_key(self):
        with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'SECRET_TEST_ONLY'},clear=True):self.assertEqual(read_key(),'SECRET_TEST_ONLY')
        for key in ('',' x','x y','中文','x\n'):
            with patch.dict(os.environ,{'DEEPSEEK_API_KEY':key},clear=True):
                with self.assertRaises(M5Error):read_key()

    def test_dry_run_and_no_evidence_never_read_key(self):
        for data,dry in ((fixture(),True),(fixture('retrieval_no_evidence'),False),(fixture('retrieval_error'),False)):
            key=Mock(side_effect=AssertionError('No key access'));api=Mock()
            result=run_pipeline(data,dry_run=dry,key_provider=key,api_call=api)
            key.assert_not_called();api.assert_not_called();self.assertFalse(result['publication_ready'])

    def test_retry_then_success_and_incomplete_cost(self):
        r,api,sleep=self.call([M5Error('API_TIMEOUT','timeout'),response(draft()),response(judge())],network_retries=1,pricing=prices())
        self.assertEqual(r['status'],'ANSWERED');self.assertEqual(api.call_count,3);sleep.assert_called_once_with(1)
        self.assertEqual(r['logical_calls'],2);self.assertEqual(r['network_retry_count'],1)
        self.assertIsNone(r['billing']['total_cost']);self.assertEqual(r['billing']['known_response_cost'],'0.00044')
        self.assertFalse(r['repair_used']);export_pipeline_contracts(r)

    def test_retry_exhaustion_is_technical_error(self):
        r,api,_=self.call([M5Error('HTTP_503','unavailable')]*2,network_retries=1)
        self.assertEqual(api.call_count,2);self.assertEqual(r['error']['code'],'HTTP_503');self.assertFalse(r['repair_used'])
        self.assertEqual(r['status'],'ERROR');self.assertEqual(r['answer'],'')

    def test_auth_never_retries(self):
        for code in ('HTTP_400','HTTP_401','HTTP_402','HTTP_403','HTTP_422','UNEXPECTED_REDIRECT'):
            r,api,sleep=self.call([M5Error(code,'fixture')],network_retries=1)
            self.assertEqual(api.call_count,1);sleep.assert_not_called();self.assertEqual(r['error']['code'],code)

    def test_max_eight_requests_one_shared_content_repair(self):
        values=[]
        for content in (draft(),judge(False),draft(),judge()):values.extend([M5Error('HTTP_429','limited'),response(content)])
        r,api,_=self.call(values,network_retries=1)
        self.assertEqual(r['status'],'ANSWERED');self.assertEqual(api.call_count,8)
        self.assertEqual(r['max_api_calls'],8);self.assertEqual(r['logical_calls'],4)
        self.assertTrue(r['repair_used']);self.assertEqual(r['network_retry_count'],4)
        export_pipeline_contracts(r)

    def test_json_failure_uses_repair_not_network_retry(self):
        r,api,sleep=self.call([response('bad json'),response(draft()),response(judge())],network_retries=1)
        self.assertEqual(r['status'],'ANSWERED');self.assertEqual(api.call_count,3)
        self.assertTrue(r['repair_used']);self.assertEqual(r['network_retry_count'],0);sleep.assert_not_called()

    def test_two_parse_failures_stay_blocked(self):
        r,api,_=self.call([response('bad json'),response('bad json')],network_retries=1)
        self.assertEqual(r['gate'],'BLOCKED');self.assertEqual(api.call_count,2);self.assertEqual(r['answer'],'')

    def test_interrupt_tracks_unknown_provider_outcome(self):
        r,api,_=self.call([KeyboardInterrupt()],network_retries=1,pricing=prices())
        self.assertEqual(r['error']['code'],'CANCELLED');self.assertIsNone(r['billing']['total_cost'])
        self.assertEqual(r['api_calls'][0]['state'],'INTERRUPTED_OUTCOME_UNKNOWN')

    def test_unknown_transport_exception_does_not_leak(self):
        r,api,_=self.call([RuntimeError('SECRET_TEST_ONLY')],network_retries=1)
        self.assertEqual(r['error']['code'],'UNEXPECTED_TRANSPORT_ERROR');self.assertEqual(api.call_count,1)

    def test_legacy_default_keeps_no_retry(self):
        r,api,_=self.call([M5Error('API_TIMEOUT','fixture')])
        self.assertEqual(api.call_count,1);self.assertEqual(r['max_api_calls'],4)

    def test_cost_covers_generation_and_review(self):
        r,_,_=self.call([response(draft()),response(judge())],pricing=prices())
        self.assertTrue(r['billing']['complete']);self.assertEqual(r['billing']['total_cost'],'0.00044')

    def test_four_statuses_have_public_contracts(self):
        records=[]
        for status in ('ANSWERED','PARTIAL'):
            r,_,_=self.call([response(draft(status)),response(judge(status=status))]);records.append(r)
        records.append(run_pipeline(fixture('retrieval_no_evidence')))
        records.append(run_pipeline(fixture('retrieval_error')))
        self.assertEqual([r['status'] for r in records],['ANSWERED','PARTIAL','INSUFFICIENT_SOURCES','ERROR'])
        for record in records:export_pipeline_contracts(record)


class BillingTests(unittest.TestCase):
    def call(self):return {'state':'RECEIVED','input_tokens':100,'output_tokens':20,'cache_hit_tokens':40,'cache_miss_tokens':60,
                         'requested_model':'deepseek-flash','returned_model':'deepseek-flash'}

    def test_no_prices_unknown_not_zero(self):
        r=summarize_calls([self.call()],None,'deepseek-flash');self.assertIsNone(r['total_cost']);self.assertFalse(r['complete'])

    def test_no_requests_zero(self):self.assertEqual(summarize_calls([],None,'deepseek-flash')['total_cost'],'0')

    def test_missing_usage_unknown(self):
        c=self.call();c['input_tokens']=None
        self.assertIsNone(summarize_calls([c],prices(),'deepseek-flash')['total_cost'])

    def test_missing_cache_split_with_different_rates_unknown(self):
        c=self.call();c['cache_hit_tokens']=None
        self.assertIsNone(summarize_calls([c],prices(),'deepseek-flash')['total_cost'])

    def test_alias_pricing_mismatch_not_guessed(self):
        c=self.call();c['returned_model']='different-model'
        self.assertIsNone(summarize_calls([c],prices(),'deepseek-flash')['total_cost'])

    def test_invalid_prices_rejected(self):
        for value in (None,-1,True,'NaN','Infinity'):
            p=prices();p['output_per_million']=value
            with self.assertRaises(M5Error):validate_pricing(p,'deepseek-flash')


class BBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def a_run(self):
        inp=self.root/'questions.jsonl'
        inp.write_text('{"id":"a","question":"first"}\n{bad\n{"id":"b","question":"second"}\n',encoding='utf-8')
        out=self.root/'a'
        run_batch(load_requests(inp),a_helpers.config(),out,lambda:a_helpers.BatchTests().workshop(),input_sha256=sha_file(inp))
        return out

    def test_mixed_batch_preserves_rows_and_does_not_call_api(self):
        a=self.a_run();out=self.root/'b'
        with patch.dict(os.environ,{},clear=True):r=run_saved_batch(a,out)
        self.assertEqual(r['status'],'COMPLETED_WITH_ERRORS');self.assertEqual(r['api_requests'],0)
        rows=[json.loads(l) for l in (out/'predictions.jsonl').read_text().splitlines()]
        self.assertEqual([v['status'] for v in rows],['READY_FOR_PIPELINE','ERROR','READY_FOR_PIPELINE'])
        self.assertTrue(all(v['local_contract_checks']=='PASS' for v in rows))
        self.assertEqual(rows[1]['upstream_error']['code'],'INVALID_JSON')

    def test_modified_packed_file_is_rejected_before_pipeline(self):
        a=self.a_run();p=a/'item_0001/retrieval.json';p.write_bytes(p.read_bytes()+b' ')
        runner=Mock()
        with self.assertRaises(M5Error):run_saved_batch(a,self.root/'b',generate=True,pipeline_fn=runner)
        runner.assert_not_called();self.assertFalse((self.root/'b').exists())

    def test_no_overwrite(self):
        a=self.a_run();out=self.root/'b';out.mkdir();(out/'sentinel').write_text('keep')
        with self.assertRaises(FileExistsError):run_saved_batch(a,out)
        self.assertEqual((out/'sentinel').read_text(),'keep')

    def test_stop_after_missing_key(self):
        a=self.a_run();out=self.root/'b'
        with patch.dict(os.environ,{},clear=True):r=run_saved_batch(a,out,generate=True)
        rows=[json.loads(l) for l in (out/'predictions.jsonl').read_text().splitlines()]
        self.assertEqual(rows[0]['error']['code'],'MISSING_API_KEY')
        self.assertEqual(rows[2]['error']['code'],'BATCH_ABORTED');self.assertEqual(r['api_requests'],0)

    def test_input_limit_before_pipeline(self):
        a=self.a_run();runner=Mock()
        with self.assertRaises(M5Error):run_saved_batch(a,self.root/'b',max_items=2,pipeline_fn=runner)
        runner.assert_not_called()

    def test_traversal_rejected_even_with_updated_manifest_hash(self):
        a=self.a_run();p=a/'results.jsonl';rows=[json.loads(l) for l in p.read_text().splitlines()]
        rows[0]['packed_file']='../outside.json'
        p.write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
        m=json.loads((a/'run.json').read_text());m['results_sha256']=sha_file(p);write_json(a/'run.json',m)
        with self.assertRaises(M5Error):load_a_run(a)

    def test_cli_live_route_removes_key_from_m4_environment(self):
        from scripts.m5_generation import b_cli
        output=self.root/'live_b'
        seen=[]
        def fake_runner(command,**kwargs):
            seen.append(kwargs['env'])
            inp=Path(command[command.index('--input-jsonl')+1])
            target=Path(command[command.index('--output-dir')+1])
            run_batch(load_requests(inp),a_helpers.config(),target,lambda:a_helpers.BatchTests().workshop())
            return 0
        argv=['b_cli','--question','What happened?','--work-base',str(self.root),'--output-dir',str(output),'--dry-run']
        with patch('sys.argv',argv),patch.object(b_cli,'run_process',side_effect=fake_runner),patch.dict(os.environ,{'DEEPSEEK_API_KEY':'SECRET_TEST_ONLY'}):
            code=b_cli.main()
        self.assertEqual(code,0);self.assertEqual(len(seen),1)
        self.assertNotIn('DEEPSEEK_API_KEY',seen[0])
        for path in output.rglob('*.json'):
            self.assertNotIn('SECRET_TEST_ONLY',path.read_text(encoding='utf-8'))

    def test_batch_exception_preserves_partial_checkpoint(self):
        a=self.a_run();out=self.root/'b'
        def failed(*args,**kwargs):
            kwargs['checkpoint']({'status':'RUNNING','api_calls':[{'state':'STARTING'}]})
            raise RuntimeError('fixture')
        with self.assertRaises(RuntimeError):run_saved_batch(a,out,generate=True,pipeline_fn=failed)
        state=json.loads((out/'run.json').read_text())
        self.assertEqual(state['status'],'FAILED');self.assertIsNone(state['api_requests']);self.assertIsNone(state['billing'])
        self.assertTrue((out/'item_0001/pipeline.json').is_file())


if __name__=='__main__':unittest.main()
