"""Offline bridge tests. Mocked retrieval/reviews do not demonstrate live model quality."""
import copy
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.m5_live import cli
from scripts.m5_live.common import ARCHIVE_SHA, MODEL, REVISION, LiveError, inspect_paths, sha_file, read_json, write_json
from scripts.m5_live.retrieval_worker import verify_distance
from scripts.m5_generation.pipeline import run_pipeline
from scripts.m5_generation.public_contracts import export_pipeline_contracts
from test_m5_pipeline import fixture, envelope, draft, judge

ROOT=Path(__file__).resolve().parents[1]


class LiveEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.work=self.base/'work with spaces'
        self.data=self.work/'m3_data'
        self.db=self.work/'runtime_chroma'
        self.db.mkdir(parents=True)
        with closing(sqlite3.connect(self.db/'chroma.sqlite3')) as db:
            db.execute('CREATE TABLE collections (name TEXT, schema_str TEXT)')
            schema={'keys':{'#embedding':{'float_list':{'vector_index':{'enabled':True,'config':{'space':'cosine'}}}}}}
            db.execute('INSERT INTO collections VALUES (?, ?)',('test_collection',json.dumps(schema)))
            db.commit()
        write_json(self.db/'.m4_copy_ready.json',{'archive_sha256':ARCHIVE_SHA})
        write_json(self.data/'data/documents/documents.jsonl',{})
        write_json(self.work/'model_cache'/('models--'+MODEL.replace('/','--'))/'snapshots'/REVISION/'config.json',{})
        for strategy in 'ABC':
            chunk=self.data/'data/chunks'/('chunks_'+strategy+'.jsonl')
            write_json(chunk,{'test':'fixture'})
            write_json(self.data/'data/vector_store/manifests'/('chunks_'+strategy.lower()+'_test.manifest.json'),
                {'schema_version':'embedding_index.manifest.v1','embedding':{'backend':'sentence-transformers',
                  'model':MODEL,'revision':REVISION,'dimension':384,'normalization':'L2'},
                 'input':{'strategy':strategy,'path':'data/chunks/chunks_'+strategy+'.jsonl','sha256':sha_file(chunk)},
                 'chunk_count':1,'vector_store':{'distance':'cosine','collection':'test_collection'}})
        self.out=self.base/'output with spaces'
        self.stages=[]
        self.api_calls=[]
        self.record=fixture()

    def args(self,*extra):
        return cli.parser().parse_args(['--question',self.record['query'],'--work-base',str(self.work),
            '--m4-python',sys.executable,'--m5-python',sys.executable,'--output-dir',str(self.out),*extra])

    def runner(self,command,*,stage,cwd,env,timeout):
        self.stages.append(stage)
        def value(flag):return command[command.index(flag)+1]
        if stage.endswith('_environment'):
            write_json(value('--output'),{'status':'PASS','role':value('--role')})
        elif stage=='live_retrieval':
            req=read_json(value('--request'))
            r=copy.deepcopy(self.record);r['query']=req['question'];r['retrieval_query']=req['question']
            r.pop('fixture',None);r['schema_version']='retrieval_response.v2'
            config=req['retrieval_config']
            r['config']={k:config[k] for k in ('mode','top_k','candidate_k','rrf_constant')}
            if r['status']!='ERROR':
                r['index']={'strategy':config['strategy'],'collection':'test_collection',
                    'manifest_sha256':sha_file(self.data/'data/vector_store/manifests'/('chunks_'+config['strategy'].lower()+'_test.manifest.json'))}
            for row in r['results']:
                row['retrieved_by']=['bm25'];row['scores']['bm25']=1.0;row['scores']['rrf']=1/(60+row['rank'])
            wrapper={'retrieval':r,'selected_chunk_ids':[row['chunk_id'] for row in r['results']],
                     'context_tokens':0,'context':''.join(f"[{row['chunk_id']}] {row['citation']['title']}\n{row['citation']['url']}\n{row['text']}\n\n" for row in r['results'])}
            write_json(value('--output'),wrapper)
            write_json(Path(value('--output')).parent/'m4_startup.json',{'status':'PASS','live_retrieval_completed':True,
                       'retrieval_file_sha256':sha_file(value('--output'))})
        elif stage=='m5_pipeline':
            is_dry='--dry-run' in command
            api=Mock(side_effect=[envelope(draft()),envelope(judge())])
            r=run_pipeline(read_json(value('--input')),dry_run=is_dry,api_call=api,key_provider=lambda:'TEST_SECRET_NOT_FOR_NETWORK')
            self.api_calls.append(api.call_count)
            r.update(input_file=str(Path(value('--input')).resolve()),input_file_sha256=sha_file(value('--input')))
            write_json(Path(value('--output-dir'))/'pipeline.json',r)
            return 1 if r['status']=='ERROR' else 0
        elif stage=='public_contract_checks':
            p=read_json(value('--pipeline'));artifacts=export_pipeline_contracts(p)
            for name,data in artifacts.items():write_json(Path(value('--output-dir'))/name,data)
            write_json(Path(value('--output-dir'))/'summary.json',{'local_contract_checks':'PASS',
                'source_pipeline_sha256':sha_file(value('--pipeline')),'artifacts':list(artifacts)})
        else:raise AssertionError(stage)
        return 0

    def execute(self,*extra,runner=None):
        return cli.execute(self.args(*extra),project=ROOT,runner=runner or self.runner)

    def test_default_live_dry_run_no_api(self):
        r=self.execute()
        self.assertEqual(r['status'],'READY_FOR_PIPELINE')
        self.assertTrue(r['live_retrieval_completed'])
        self.assertEqual(r['local_contract_checks'],'PASS')
        self.assertEqual(r['api_calls'],0);self.assertEqual(self.api_calls,[0])
        self.assertNotIn('TEST_SECRET',json.dumps(r))

    def test_check_only_does_not_start_retrieval(self):
        r=self.execute('--check-only')
        self.assertEqual(r['status'],'ENVIRONMENT_READY')
        self.assertFalse(r['live_retrieval_completed'])
        self.assertEqual(self.stages,['m4_environment','m5_environment'])

    def test_generate_two_mock_calls(self):
        r=self.execute('--generate')
        self.assertEqual(r['status'],'ANSWERED');self.assertEqual(r['api_calls'],2)
        self.assertFalse(r['publication_ready']);self.assertEqual(r['contract_artifacts'],7)

    def test_no_evidence_remains_refusal_zero_calls(self):
        self.record=fixture('retrieval_no_evidence')
        r=self.execute('--generate')
        self.assertEqual(r['status'],'INSUFFICIENT_SOURCES');self.assertEqual(r['api_calls'],0)

    def test_retrieval_error_remains_error_zero_calls(self):
        self.record=fixture('retrieval_error')
        r=self.execute('--generate')
        self.assertEqual(r['status'],'ERROR');self.assertEqual(r['api_calls'],0)
        self.assertEqual(r['contract_artifacts'],1)

    def test_process_failure_prevents_generation(self):
        def broken(cmd,**kw):
            if kw['stage']=='live_retrieval':return 7
            return self.runner(cmd,**kw)
        r=self.execute('--generate',runner=broken)
        self.assertEqual(r['error']['code'],'LIVE_RETRIEVAL_FAILED')
        self.assertEqual(r['api_calls'],0);self.assertNotIn('m5_pipeline',self.stages)

    def test_env_failure_prevents_retrieval(self):
        r=self.execute(runner=lambda *a,**kw:1)
        self.assertEqual(r['error']['code'],'ENVIRONMENT_CHECK_FAILED')
        self.assertFalse(r['live_retrieval_completed']);self.assertEqual(r['api_calls'],0)

    def test_wrong_question_prevents_generation(self):
        def broken(cmd,**kw):
            code=self.runner(cmd,**kw)
            if kw['stage']=='live_retrieval':
                path=self.out/'retrieval.json';r=read_json(path);r['retrieval']['query']='Wrong question';write_json(path,r)
            return code
        r=self.execute('--generate',runner=broken)
        self.assertEqual(r['error']['code'],'QUERY_MISMATCH');self.assertNotIn('m5_pipeline',self.stages)

    def test_startup_hash_binding(self):
        def broken(cmd,**kw):
            code=self.runner(cmd,**kw)
            if kw['stage']=='live_retrieval':
                path=self.out/'m4_startup.json';r=read_json(path);r['retrieval_file_sha256']='0'*64;write_json(path,r)
            return code
        r=self.execute(runner=broken)
        self.assertEqual(r['error']['code'],'RETRIEVAL_BINDING_ERROR')

    def test_pipeline_hash_binding(self):
        def broken(cmd,**kw):
            code=self.runner(cmd,**kw)
            if kw['stage']=='m5_pipeline':
                path=self.out/'pipeline/pipeline.json';r=read_json(path);r['input_file_sha256']='0'*64;write_json(path,r)
            return code
        r=self.execute(runner=broken)
        self.assertEqual(r['error']['code'],'PIPELINE_BINDING_ERROR')

    def test_contract_failure_does_not_claim_success(self):
        def broken(cmd,**kw):
            if kw['stage']=='public_contract_checks':return 1
            return self.runner(cmd,**kw)
        r=self.execute('--generate',runner=broken)
        self.assertEqual(r['status'],'ERROR');self.assertEqual(r['api_calls'],2)
        self.assertEqual(r['error']['code'],'PUBLIC_CONTRACT_CHECK_FAILED')

    def test_generation_interrupt_keeps_api_outcome_unknown(self):
        def broken(cmd,**kw):
            if kw['stage']=='m5_pipeline':raise KeyboardInterrupt()
            return self.runner(cmd,**kw)
        r=self.execute('--generate',runner=broken)
        self.assertEqual(r['error']['code'],'CANCELLED');self.assertIsNone(r['api_calls'])
        self.assertEqual(read_json(self.out/'run.json')['status'],'ERROR')

    def test_existing_output_never_overwritten(self):
        self.out.mkdir();(self.out/'keep.txt').write_text('unchanged')
        with self.assertRaises(LiveError):self.execute()
        self.assertEqual((self.out/'keep.txt').read_text(),'unchanged');self.assertEqual(self.stages,[])

    def test_invalid_options_fail_before_output_or_child(self):
        for options in [('--question',' '),('--top-k','31'),('--rrf-constant','0'),('--context-tokens','0'),
                        ('--retrieval-timeout','1'),('--question','x'*8001)]:
            with self.subTest(options=options),self.assertRaises(LiveError):self.execute(*options)
        self.assertFalse(self.out.exists());self.assertEqual(self.stages,[])

    def test_special_characters_are_question_data_not_commands(self):
        question='What does `echo` mean? $(not-a-command) & "quoted"'
        r=self.execute('--question',question)
        self.assertEqual(r['question'],question);self.assertEqual(r['status'],'READY_FOR_PIPELINE')

    def test_m4_does_not_inherit_deepseek_key(self):
        seen=[]
        def inspect(cmd,**kw):
            if kw['stage'] in ('m4_environment','live_retrieval','public_contract_checks'):
                seen.append(kw['env']);self.assertNotIn('DEEPSEEK_API_KEY',kw['env'])
            self.assertNotIn('TEST_KEY',json.dumps(cmd))
            return self.runner(cmd,**kw)
        with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'TEST_KEY'}):self.execute(runner=inspect)
        self.assertEqual(len(seen),3)

    def test_path_preflight_checks_marker_cache_and_manifests(self):
        self.assertEqual(inspect_paths(self.work)['db'],self.db.resolve())
        marker=self.db/'.m4_copy_ready.json';write_json(marker,{'archive_sha256':'wrong'})
        with self.assertRaisesRegex(LiveError,'readiness marker'):inspect_paths(self.work)
        write_json(marker,{'archive_sha256':ARCHIVE_SHA})
        config=self.work/'model_cache'/('models--'+MODEL.replace('/','--'))/'snapshots'/REVISION/'config.json'
        config.unlink()
        with self.assertRaisesRegex(LiveError,'snapshot'):inspect_paths(self.work)

    def test_ambiguous_manifest_fails_closed(self):
        path=self.data/'data/vector_store/manifests/chunks_a_extra.manifest.json';write_json(path,{})
        with self.assertRaisesRegex(LiveError,'Exactly one'):inspect_paths(self.work)

    def test_manifest_cannot_escape_data_root(self):
        path=self.data/'data/vector_store/manifests/chunks_a_test.manifest.json';m=read_json(path)
        m['input']['path']='../../runtime_chroma/chroma.sqlite3';write_json(path,m)
        with self.assertRaisesRegex(LiveError,'unsafe'):inspect_paths(self.work)

    def test_persisted_cosine_and_conflicting_metadata(self):
        verify_distance(self.db,'test_collection',{})
        with self.assertRaises(LiveError):verify_distance(self.db,'test_collection',{'hnsw:space':'l2'})
        with self.assertRaises(LiveError):verify_distance(self.db,'missing',{})

    def test_child_process_timeout_is_stopped_without_retry(self):
        process=Mock();process.wait.side_effect=[subprocess.TimeoutExpired('test',30),0];process.poll.return_value=None
        with patch('scripts.m5_live.cli.subprocess.Popen',return_value=process), \
             patch('scripts.m5_live.cli.time.monotonic',side_effect=[0,0,61]):
            with self.assertRaisesRegex(LiveError,'timed out'):
                cli.run_process(['python'],stage='test',cwd=ROOT,env={},timeout=60)
        process.terminate.assert_called_once()

    def test_check_only_allows_no_question(self):
        args=self.args('--check-only');args.question=None
        r=cli.execute(args,project=ROOT,runner=self.runner)
        self.assertEqual(r['status'],'ENVIRONMENT_READY')

    def test_cli_help_has_no_import_of_heavy_m4_dependencies(self):
        result=subprocess.run([sys.executable,'-B','-m','scripts.m5_live.cli','--help'],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('--generate',result.stdout);self.assertIn('--check-only',result.stdout)

    def test_m5_and_contract_real_subprocess_bridge(self):
        def hybrid_runner(command,**kwargs):
            if kwargs['stage'] in ('m5_pipeline','public_contract_checks'):
                return subprocess.run(command,cwd=kwargs['cwd'],env=kwargs['env'],
                    capture_output=True,text=True,encoding='utf-8',timeout=60).returncode
            return self.runner(command,**kwargs)
        r=self.execute(runner=hybrid_runner)
        self.assertEqual(r['status'],'READY_FOR_PIPELINE',r.get('error'))
        self.assertEqual(r['local_contract_checks'],'PASS')
        self.assertEqual(r['api_calls'],0)

    def test_config_mismatch_blocks_generation(self):
        def broken(cmd,**kw):
            code=self.runner(cmd,**kw)
            if kw['stage']=='live_retrieval':
                path=self.out/'retrieval.json';r=read_json(path);r['retrieval']['config']['top_k']=4;write_json(path,r)
            return code
        r=self.execute('--generate',runner=broken)
        self.assertEqual(r['error']['code'],'RETRIEVAL_CONFIG_MISMATCH')
        self.assertNotIn('m5_pipeline',self.stages)


if __name__=='__main__':unittest.main()
