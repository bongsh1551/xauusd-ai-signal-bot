import unittest
from unittest.mock import Mock, patch
import twelvedata_client


class TwelveDataRetryTests(unittest.TestCase):
    def test_retries_429_once_after_retry_after_with_same_request(self):
        limited = Mock(status_code=429, headers={'Retry-After': '7'})
        success = Mock(status_code=200, headers={})
        with patch.object(twelvedata_client.requests, 'get', side_effect=[limited, success]) as get, \
             patch.object(twelvedata_client.time, 'sleep') as sleep:
            result = twelvedata_client.get('https://api.twelvedata.com/time_series',
                                           params={'apikey': 'secret'}, timeout=(10, 45))
        self.assertIs(result, success)
        sleep.assert_called_once_with(7)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0], get.call_args_list[1])

    def test_uses_safe_default_when_retry_after_missing(self):
        limited = Mock(status_code=429, headers={})
        success = Mock(status_code=200, headers={})
        with patch.object(twelvedata_client.requests, 'get', side_effect=[limited, success]), \
             patch.object(twelvedata_client.time, 'sleep') as sleep:
            twelvedata_client.get('https://api.twelvedata.com/time_series')
        sleep.assert_called_once_with(60)

    def test_does_not_retry_non_429(self):
        failure = Mock(status_code=500, headers={})
        with patch.object(twelvedata_client.requests, 'get', return_value=failure) as get, \
             patch.object(twelvedata_client.time, 'sleep') as sleep:
            result = twelvedata_client.get('https://api.twelvedata.com/time_series')
        self.assertIs(result, failure)
        get.assert_called_once()
        sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
