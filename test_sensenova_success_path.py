import os
import unittest
from unittest.mock import patch
import sensenova_runner as runner

TEXT = '状态：WAIT\n```market_watch\n{"zones": []}\n```'

class SuccessPathTests(unittest.TestCase):
    def test_success_usage_variants(self):
        usages = [
            {'prompt_tokens': 3, 'completion_tokens': 5, 'completion_tokens_details': {'reasoning_tokens': 2}},
            {'prompt_tokens': 3},
            None,
        ]
        for usage in usages:
            with self.subTest(usage=usage):
                data = {'choices': [{'finish_reason': 'stop', 'message': {'content': TEXT}}], 'usage': usage}
                with patch.dict(os.environ, {'SENSENOVA_API_KEY': 'unit-test-placeholder', 'GEMINI_API_KEY': ''}), \
                     patch.object(runner.requests, 'post') as http, \
                     patch.object(runner.pipeline, 'api_json', return_value=data), \
                     patch.object(runner.zone_lifecycle, 'apply_zone_lifecycle', return_value=(TEXT, {})):
                    response = runner.post('https://generativelanguage.googleapis.com/v1beta/models/test:generateContent',
                        json={'contents': [{'parts': [{'text': 'offline fixture'}]}]})
                    http.assert_called_once()
                    self.assertEqual(http.call_args.args[0], runner.ENDPOINT)
                    self.assertEqual(response.json()['candidates'][0]['content']['parts'][0]['text'], TEXT)
                    self.assertEqual(runner.LAST_DIAGNOSTIC['analysis_status'], 'WAIT')
                    if isinstance(usage, dict) and 'completion_tokens_details' in usage:
                        self.assertEqual(runner.LAST_DIAGNOSTIC['usage']['completion_reasoning_tokens'], 2)
                    else:
                        self.assertNotIn('completion_reasoning_tokens', runner.LAST_DIAGNOSTIC['usage'])

if __name__ == '__main__':
    unittest.main()
