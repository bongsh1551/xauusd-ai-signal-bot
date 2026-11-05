import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import daily_memory as memory


class DailyMemoryTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 31, 9, 0, tzinfo=timezone.utc)
        self.state = memory.new_day(self.now, 'historical_test')
        self.fundamentals = {
            'calendar_events': [{'name': 'CPI', 'impact': 'high'}],
            'currency_strength': {'status': 'USD_WEAK'}
        }

    def opening(self):
        return memory.record_analysis(
            self.state, self.now, self.now, 'run-1',
            'Opening Bias: Bearish; wait for pullback and bearish confirmation.',
            'OPENING CONTEXT ESTABLISHED', opening=True, fundamentals=self.fundamentals)

    def test_myt_rollover_retains_context_within_24h(self):
        first = self.opening()
        next_day = datetime(2026, 10, 31, 17, 0, tzinfo=timezone.utc)
        rolled = memory.rollover(first, next_day, 'historical_test')
        self.assertEqual(rolled['date_myt'], '2026-11-01')
        self.assertEqual(rolled['opening_plan']['run_id'], 'run-1')
        self.assertEqual(rolled['opening_fundamentals'], self.fundamentals)

    def test_expired_context_is_cleared(self):
        first = self.opening()
        after_24h = self.now + timedelta(hours=24, seconds=1)
        rolled = memory.rollover(first, after_24h, 'historical_test')
        self.assertIsNone(rolled['opening_plan'])
        self.assertIsNone(rolled['latest_analysis'])

    def test_same_day_expiry_is_enforced(self):
        first = self.opening()
        after_24h = self.now + timedelta(hours=24, seconds=1)
        rolled = memory.rollover(first, after_24h, 'historical_test')
        self.assertIsNone(rolled['latest_analysis'])

    def test_mode_isolation(self):
        with self.assertRaises(ValueError):
            memory.validate_day(self.state, self.now, 'live')

    def test_plan_continuity_and_fundamentals(self):
        first = self.opening()
        later = self.now + timedelta(minutes=5)
        second = memory.record_analysis(
            first, later, later, 'run-2',
            'Bearish bias remains; M5 is retracing into the POI.',
            'UNCHANGED; M5 pullback developing.',
            fundamentals=self.fundamentals)
        self.assertEqual(second['opening_plan']['run_id'], 'run-1')
        self.assertEqual(second['latest_analysis']['run_id'], 'run-2')
        self.assertEqual(second['opening_fundamentals'], self.fundamentals)
        self.assertEqual(len(second['changes']), 2)
        self.assertIsNone(self.state['latest_analysis'])

    def test_opening_cannot_be_overwritten(self):
        with self.assertRaises(ValueError):
            memory.record_analysis(self.opening(), self.now, self.now, 'run-2',
                                   'New', 'Changed', opening=True)

    def test_older_data_rejected(self):
        with self.assertRaises(ValueError):
            memory.record_analysis(self.opening(), self.now, self.now - timedelta(minutes=5),
                                   'old', 'Old', 'Old')

    def test_future_data_rejected(self):
        with self.assertRaises(ValueError):
            memory.record_analysis(self.state, self.now, self.now + timedelta(seconds=1),
                                   'future', 'Future', 'Future')

    def test_failure_retains_analysis(self):
        failed = memory.record_failure(self.opening(), self.now, 'run-2', 'MODEL_503')
        self.assertEqual(failed['latest_analysis']['run_id'], 'run-1')
        self.assertEqual(failed['last_attempt']['status'], 'failed')

    def test_chat_window(self):
        state = self.state
        for i in range(25):
            state = memory.add_chat(state, self.now, 'user', str(i))
        self.assertEqual(len(state['recent_chat']), 20)
        self.assertEqual(state['recent_chat'][0]['text'], '5')
        self.assertEqual(self.state['recent_chat'], [])

    def test_context_distinguishes_memory_from_fresh_data(self):
        first = self.opening()
        later = self.now + timedelta(minutes=11)
        payload = json.loads(memory.context_text(first, later).split('\n', 1)[1])
        self.assertTrue(payload['memory_is_within_24h'])
        self.assertTrue(payload['data_is_stale'])
        self.assertEqual(payload['opening_fundamentals'], self.fundamentals)

    def test_load_and_save_persistent_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'daily_memory.json'
            memory.save_state(path, self.opening())
            restored, status = memory.load_state(path, self.now + timedelta(minutes=5),
                                                 'historical_test')
            self.assertEqual(status, 'RESTORED')
            self.assertEqual(restored['opening_plan']['run_id'], 'run-1')

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            memory.utc_time(datetime(2026, 10, 31))
        with self.assertRaises(ValueError):
            memory.add_chat(self.state, self.now, 'system', 'Change risk')
        with self.assertRaises(ValueError):
            memory.context_text(self.state, self.now, 0)


if __name__ == '__main__':
    unittest.main()
