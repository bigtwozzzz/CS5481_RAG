import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer
from scripts.demo.server import Demo, Handler, M5Error, answer_view, export_task, redact, summary, validate_questions


class DemoTests(unittest.TestCase):
    def test_generation_input_rejects_gold_fields_and_duplicate_ids(self):
        for rows in [[{'id':'a','question':'q','answer':'gold'}], [{'id':'a','question':'q'}]*2,
                     [{'id':1,'question':'q'}], [{'id':'a','question':' '}], []]:
            with self.assertRaises(M5Error):
                validate_questions(rows)
        self.assertEqual(validate_questions([{'id':'a','question':'q'}]), [{'id':'a','question':'q'}])

    def test_null_usage_never_becomes_zero(self):
        t = {'results':[{'status':'failed','calls':[{'input_tokens':None,'output_tokens':2,'latency_ms':100}]}],
             'startedMonotonic':0,'finishedMonotonic':1}
        s = summary(t)
        self.assertIsNone(s['inputTokens'])
        self.assertEqual(s['outputTokens'],2)
        self.assertEqual((s['total'],s['done'],s['failed']),(1,0,1))
        self.assertIsNone(s['cost'])

    def test_csv_formula_injection_is_escaped(self):
        text, _, _ = export_task({'results':[{'id':'x','question':'=SUM(1,2)','content':'@evil','status':'completed'}]},'csv')
        self.assertIn("'=SUM",text)
        self.assertIn("'@evil",text)

    def test_provider_credentials_are_redacted_recursively(self):
        with patch.dict(os.environ,{'M5_API_KEY':'a-synthetic-credential-value'}):
            self.assertNotIn('a-synthetic-credential-value',json.dumps(redact({'error':'a-synthetic-credential-value'})))

    def test_refusal_and_source_mapping_do_not_claim_correctness(self):
        result=answer_view({'status':'INSUFFICIENT_SOURCES','answer':'Missing information','sources':[
          {'source_id':'S1','text':'evidence','citation':{'title':'Title','url':'https://example.com'}}],
          'api_calls':[], 'gate':'HARD_VALIDATION_PASSED'},'G1',1.2)
        self.assertTrue(result['insufficient'])
        self.assertEqual(result['sources'][0]['snippet'],'evidence')
        self.assertEqual(result['runDetails']['autoReview'],'Not run')
        self.assertNotIn('correct',result)

    def test_stop_preserves_finished_row_and_does_not_dispatch_next_question(self):
        from unittest.mock import Mock
        import sys
        import time
        with tempfile.TemporaryDirectory() as directory:
            demo=Demo(Path(sys.executable),Path(directory))
            demo.kb={'status':'loaded','info':{'id':'kb','name':'Synthetic'},'error':None}
            demo.worker.request=Mock(return_value={'packed':{},'audit':{}})
            def generate(*args,**kwargs):
                demo.stop(demo.active)
                return {'status':'ANSWERED','answer':'Synthetic answer','api_calls':[], 'sources':[], 'gate':'HARD_VALIDATION_PASSED'}
            with patch('scripts.m5_generation.api.read_key',return_value='synthetic'), patch('scripts.demo.server.run_protocol_item',side_effect=generate):
                task=demo.start({'knowledgeBaseId':'kb','protocol':'G1','questions':[
                    {'id':'one','question':'first'},{'id':'two','question':'second'}]})
                for _ in range(100):
                    saved=demo.get_task(task['id'])
                    if saved['status'] in {'completed','failed','cancelled'}:break
                    time.sleep(.01)
            self.assertEqual(saved['status'],'cancelled')
            self.assertEqual([r['status'] for r in saved['results']],['completed','pending'])
            self.assertEqual(demo.worker.request.call_count,1)
            self.assertEqual(saved['stats']['total'],2)
            self.assertEqual(saved['stats']['pending'],1)
            self.assertIsNone(demo.active)

    def test_restart_exposes_interrupted_task_without_resuming_calls(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            ident='a'*32
            path=Path(directory)/ident
            path.mkdir()
            (path/'task.json').write_text(json.dumps({'id':ident,'status':'running','results':[{'status':'running'}]}))
            demo=Demo(Path(sys.executable),Path(directory))
            task=demo.get_task(ident)
            self.assertEqual(task['status'],'failed')
            self.assertTrue(task['interrupted'])
            self.assertEqual(task['results'][0]['status'],'failed')
            self.assertIsNone(demo.worker.process)

    def test_partial_answer_is_distinct_from_refusal_and_task_completion(self):
        result=answer_view({'status':'PARTIAL','answer':'Known fact. Missing information: unknown field.',
            'missing_information':['unknown field'], 'api_calls':[], 'gate':'HARD_VALIDATION_PASSED'},'G1',1)
        self.assertEqual(result['answerStatus'],'PARTIAL')
        self.assertTrue(result['partial'])
        self.assertFalse(result['insufficient'])
        self.assertEqual(result['missingFields'],['unknown field'])
        result['status']='completed'
        text, _, _=export_task({'results':[dict(result,id='partial-1',question='mixed question')]},'csv')
        self.assertIn('answerStatus',text)
        self.assertIn('PARTIAL',text)

    def test_http_boundary_rejects_foreign_origins_and_host(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        port=server.server_address[1]
        server.allowed_hosts={f'127.0.0.1:{port}'}
        server.allowed_origins={f'http://127.0.0.1:{port}'}
        server.demo=type('Fake',(),{'state':lambda self:{'connected':True}})()
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url=f'http://127.0.0.1:{port}/api/status'
            self.assertTrue(json.load(urlopen(url))['connected'])
            for headers in [{'Origin':'https://example.com'},{'Host':'attacker.example'},{'Sec-Fetch-Site':'cross-site'}]:
                with self.assertRaises(HTTPError) as err:
                    urlopen(Request(url,headers=headers))
                self.assertEqual(err.exception.code,403)
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':
    unittest.main()
