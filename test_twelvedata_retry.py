import unittest
from unittest.mock import Mock, patch
import twelvedata_client


class TwelveDataRetryTests(unittest.TestCase):
    def test_switches_to_authorized_backup_key_after_primary_429(self):
        limited = Mock(status_code=429, headers={})
        success = Mock(status_code=200, headers={})
        with patch.object(twelvedata_client.requests, 'get', side_effect=[limited, success]) as get:
            result = twelvedata_client.get(
                'https://api.twelvedata.com/time_series',
                params={'symbol': 'XAU/USD'}, api_keys=['primary-secret', 'backup-secret'])
        self.assertIs(result, success)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0].kwargs['params']['apikey'], 'primary-secret')
        self.assertEqual(get.call_args_list[1].kwargs['params']['apikey'], 'backup-secret')

    def test_retries_last_key_once_after_retry_after(self):
        limited = Mock(status_code=429, headers={'Retry-After': '7'})
        success = Mock(status_code=200, headers={})
        with patch.object(twelvedata_client.requests, 'get', side_effect=[limited, success]) as get, \
             patch.object(twelvedata_client.time, 'sleep') as sleep:
            result = twelvedata_client.get(
                'https://api.twelvedata.com/time_series',
                params={'symbol': 'XAU/USD'}, api_keys=['primary-secret'])
        self.assertIs(result, success)
        sleep.assert_called_once_with(7)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0].kwargs['params'], get.call_args_list[1].kwargs['params'])

    def test_uses_safe_default_when_retry_after_missing(self):
        limited = Mock(status_code=429, headers={})
        success = Mock(status_code=200, headers={})
        with patch.object(twelvedata_client.requests, 'get', side_effect=[limited, success]), \
             patch.object(twelvedata_client.time, 'sleep') as sleep:
            twelvedata_client.get(
                'https://api.twelvedata.com/time_series',
                params={'symbol': 'XAU/USD'}, api_keys=['primary-secret'])
        sleep.assert_called_once_with(60)

    def test_does_not_retry_non_429(self):
        failure = Mock(status_code=500, headers={})
        with patch.object(twelvedata_client.requests, 'get', return_value=failure) as get, \
             patch.object(twelvedata_client.time, 'sleep') as sleep:
            result = twelvedata_client.get('https://api.twelvedata.com/time_series',
                                           params={'symbol': 'XAU/USD'},
                                           api_keys=['primary-secret'])
        self.assertIs(result, failure)
        get.assert_called_once()
        sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
