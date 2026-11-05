import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import fundamentals


def fx_value(symbol):
    return {
        'symbol': symbol,
        'last_close': 1.0,
        'change_4h_pct': -0.1 if symbol == 'EUR/USD' else 0.1,
        'last_closed_utc': '2026-11-05T00:00:00+00:00',
        'closed_h1_candles': 10,
        'minutes_since_close': 5,
        'stale': False,
    }


class FxCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.cache_path = root / '.cache' / 'fx_strength.json'
        self.updated_path = root / '.cache' / 'fx_strength.updated'
        self.folder = root / 'journal'
        self.folder.mkdir()
        self.now = pd.Timestamp('2026-11-05T02:00:00Z')
        self.patches = [
            patch.object(fundamentals, 'FX_CACHE_PATH', self.cache_path),
            patch.object(fundamentals, 'FX_CACHE_UPDATED', self.updated_path),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def calendar(self, now, folder):
        return {'status': 'no_events', 'events': [], 'coverage': 'full',
                'requested_horizon_end_utc': (now + pd.Timedelta(hours=24)).isoformat()}

    def test_fresh_cache_avoids_both_fx_api_calls(self):
        fundamentals.save_fx_cache({
            'EUR/USD': {'cached_at_utc': self.now.isoformat(), 'data': fx_value('EUR/USD')},
            'USD/JPY': {'cached_at_utc': self.now.isoformat(), 'data': fx_value('USD/JPY')},
        }, self.now)
        with patch.object(fundamentals, 'fetch_calendar', side_effect=self.calendar), \
             patch.object(fundamentals, 'fetch_fx') as fetch:
            result = fundamentals.collect_fundamentals('key', self.now + pd.Timedelta(minutes=5), self.folder)
        fetch.assert_not_called()
        self.assertEqual(result['currency_strength']['status'], 'USD_STRONG')
        self.assertEqual(result['currency_strength']['data_source'], 'cache')

    def test_failed_pair_has_15_minute_retry_cooldown_and_success_is_reused(self):
        def fetch(key, symbol, now, folder):
            if symbol == 'EUR/USD':
                raise RuntimeError('temporary provider failure')
            return fx_value(symbol)

        with patch.object(fundamentals, 'fetch_calendar', side_effect=self.calendar), \
             patch.object(fundamentals, 'fetch_fx', side_effect=fetch) as mocked:
            first = fundamentals.collect_fundamentals('key', self.now, self.folder)
            self.assertEqual(mocked.call_count, 2)
            self.assertEqual(first['currency_strength']['status'], 'UNAVAILABLE')

            mocked.reset_mock()
            second = fundamentals.collect_fundamentals(
                'key', self.now + pd.Timedelta(minutes=5), self.folder)
            mocked.assert_not_called()
            self.assertEqual(second['currency_strength']['status'], 'UNAVAILABLE')

            mocked.reset_mock()
            third = fundamentals.collect_fundamentals(
                'key', self.now + pd.Timedelta(minutes=16), self.folder)
            mocked.assert_called_once()
            self.assertEqual(mocked.call_args.args[1], 'EUR/USD')
            self.assertEqual(third['currency_strength']['status'], 'USD_STRONG')

    def test_expired_pair_is_not_returned_from_cache(self):
        fundamentals.save_fx_cache({
            'EUR/USD': {'cached_at_utc': (self.now - pd.Timedelta(minutes=75)).isoformat(),
                        'data': fx_value('EUR/USD')},
            'USD/JPY': {'cached_at_utc': self.now.isoformat(), 'data': fx_value('USD/JPY')},
        }, self.now - pd.Timedelta(minutes=75))
        loaded = fundamentals.load_fx_cache(self.now)
        self.assertNotIn('EUR/USD', loaded['symbols'])
        self.assertIn('USD/JPY', loaded['symbols'])


if __name__ == '__main__':
    unittest.main()
