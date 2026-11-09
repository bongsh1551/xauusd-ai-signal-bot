import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch
import requests
import sensenova_transport as t

class SenseNovaRetryTests(unittest.TestCase):
    def response(self, status, retry_after=None):
        r = Mock(status_code=status)
        r.headers = {} if retry_after is None else {'Retry-After': retry_after}
        return r
    def case(self, outcomes):
        session, sleep = Mock(), Mock()
        session.post.side_effect = outcomes
        options = {'json': {'messages': [{'content': [
            {'type': 'text', 'text': 'PRIVATE'},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA'}}
        ]}]}, 'timeout': (10,120)}
        return session, sleep, options
    def call(self,s,w,o):
        with redirect_stdout(io.StringIO()):
            return t.request_with_retry(s,'endpoint',o,w)
    def test_first_success(self):
        r=self.response(200); s,w,o=self.case([r])
        self.assertIs(self.call(s,w,o),r)
        self.assertEqual(s.post.call_count,1); w.assert_not_called()
    def test_recovery(self):
        r=self.response(200); s,w,o=self.case([requests.ReadTimeout('SECRET'),r])
        self.assertIs(self.call(s,w,o),r)
        self.assertEqual(s.post.call_count,2); w.assert_called_once_with(5)
        self.assertTrue(all(c.kwargs==o for c in s.post.call_args_list))
    def test_exhausted(self):
        s,w,o=self.case([requests.ConnectionError('SECRET')]*3)
        with self.assertRaisesRegex(t.SenseNovaRequestFailed,'attempts=3'): self.call(s,w,o)
        self.assertEqual(s.post.call_count,3)
        self.assertEqual([c.args for c in w.call_args_list],[(5,),(5,)])
    def test_status_recovery(self):
        r=self.response(200); s,w,o=self.case([self.response(503),self.response(502),r])
        self.assertIs(self.call(s,w,o),r)
        self.assertEqual(s.post.call_count,3); self.assertEqual(w.call_count,2)
    def test_permanent_errors(self):
        for status in (400,401,403,404,413):
            with self.subTest(status=status):
                s,w,o=self.case([self.response(status)])
                with self.assertRaises(t.SenseNovaRequestFailed): self.call(s,w,o)
                self.assertEqual(s.post.call_count,1); w.assert_not_called()
    def test_long_retry_after(self):
        s,w,o=self.case([self.response(429,'60')])
        with self.assertRaisesRegex(t.SenseNovaRequestFailed,'RETRY_AFTER'): self.call(s,w,o)
        self.assertEqual(s.post.call_count,1); w.assert_not_called()
    def test_ssl_and_proxy_fail_fast(self):
        for exc in (requests.exceptions.SSLError('SECRET'),requests.exceptions.ProxyError('SECRET')):
            s,w,o=self.case([exc])
            with self.assertRaises(t.SenseNovaRequestFailed): self.call(s,w,o)
            self.assertEqual(s.post.call_count,1); w.assert_not_called()
    def test_safe_diagnostics(self):
        s,w,o=self.case([requests.Timeout('SECRET')]*3)
        log=io.StringIO()
        with redirect_stdout(log),self.assertRaises(t.SenseNovaRequestFailed):
            t.request_with_retry(s,'endpoint',o,w)
        self.assertNotIn('SECRET',log.getvalue())
        self.assertNotIn('PRIVATE',log.getvalue())
        self.assertNotIn('AAAA',log.getvalue())
        result=t.payload_diagnostics(o['json'])
        self.assertEqual(result['image_count'],1)
        self.assertEqual(result['image_base64_chars'],4)
    def test_nested_error_chain_is_logged_without_messages(self):
        inner=requests.Timeout('INNER_SECRET')
        outer=requests.ConnectionError('OUTER_SECRET')
        outer.__cause__=inner
        s,w,o=self.case([outer])
        log=io.StringIO()
        with redirect_stdout(log),self.assertRaises(t.SenseNovaRequestFailed):
            t.request_with_retry(s,'endpoint',o,w)
        line=json.loads(log.getvalue().strip().splitlines()[0])
        self.assertEqual(line['error_chain'],['ConnectionError','Timeout'])
        self.assertNotIn('SECRET',log.getvalue())
    def test_install_disables_gemini_and_nested_retries(self):
        runner=SimpleNamespace(ENDPOINT='https://token.sensenova.ai/v1/chat/completions')
        with patch.object(t.requests,'Session') as factory,patch.object(t.requests,'post') as network:
            t.install(runner)
            adapter=factory.return_value.mount.call_args.args[1]
            self.assertEqual(adapter.max_retries.total,0)
            with self.assertRaises(t.SenseNovaRequestFailed): runner.gemini_post_with_retry('anything',{})
            with self.assertRaises(t.SenseNovaRequestFailed):
                runner.requests.post('https://generativelanguage.googleapis.com/test')
            network.assert_not_called(); factory.return_value.post.assert_not_called()
            t.install(runner); self.assertEqual(factory.call_count,1)
    def test_endpoint_is_used_and_redirects_disabled(self):
        runner=SimpleNamespace(ENDPOINT='https://token.sensenova.ai/v1/chat/completions')
        with patch.object(t.requests,'Session') as factory:
            factory.return_value.post.return_value=self.response(200)
            t.install(runner)
            with redirect_stdout(io.StringIO()): runner.requests.post(runner.ENDPOINT,json={'messages':[]})
            args=factory.return_value.post.call_args
            self.assertEqual(args.args[0],runner.ENDPOINT)
            self.assertFalse(args.kwargs['allow_redirects'])
            self.assertEqual(args.kwargs['timeout'],(10,120))

    def test_payload_byte_count_and_multiple_images(self):
        payload={'messages':[{'content':[
            {'type':'text','text':'private prompt'},
            {'type':'image_url','image_url':{'url':'data:image/png;base64,QUJDREVGRw=='}},
            {'type':'image_url','image_url':{'url':'data:image/png;base64,SElKS0w='}}
        ]}]}
        value=t.payload_diagnostics(payload)
        self.assertEqual(value['request_json_bytes'],len(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode('utf-8')))
        self.assertEqual(value['image_count'],2)
        self.assertEqual(value['image_base64_chars'],20)
        self.assertEqual(value['message_count'],1)
        self.assertNotIn('private prompt',json.dumps(value))
        self.assertNotIn('QUJDREVGRw==',json.dumps(value))

if __name__ == '__main__':
    unittest.main()
