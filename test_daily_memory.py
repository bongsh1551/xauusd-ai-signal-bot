import json
import unittest
from datetime import datetime, timedelta, timezone
import daily_memory as memory

class DailyMemoryTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 31, 9, 0, tzinfo=timezone.utc)
        self.state = memory.new_day(self.now, 'historical_test')

    def opening(self):
        return memory.record_analysis(self.state, self.now, self.now, 'run-1',
                                      'Bearish; wait for pullback.', 'Initial test plan.', opening=True)

    def test_myt_rollover(self):
        moment = datetime(2026, 10, 31, 16, 0, tzinfo=timezone.utc)
        self.assertEqual(memory.new_day(moment, 'live')['date_myt'], '2026-11-01')
        with self.assertRaises(ValueError):
            memory.validate_day(self.state, moment, 'historical_test')

    def test_mode_isolation(self):
        with self.assertRaises(ValueError):
            memory.validate_day(self.state, self.now, 'live')

    def test_plan_continuity(self):
        first = self.opening()
        later = self.now + timedelta(minutes=5)
        second = memory.record_analysis(first, later, later, 'run-2',
                                        'Sell idea invalidated; reassessing.', 'Structure changed.')
        self.assertEqual(second['opening_plan']['run_id'], 'run-1')
        self.assertEqual(second['latest_analysis']['run_id'], 'run-2')
        self.assertEqual(len(second['changes']), 2)
        self.assertIsNone(self.state['latest_analysis'])
        self.assertEqual(first['latest_analysis']['run_id'], 'run-1')

    def test_opening_cannot_be_overwritten(self):
        with self.assertRaises(ValueError):
            memory.record_analysis(self.opening(), self.now, self.now, 'run-2', 'New', 'Changed', opening=True)

    def test_older_data_rejected(self):
        with self.assertRaises(ValueError):
            memory.record_analysis(self.opening(), self.now, self.now - timedelta(minutes=5), 'old', 'Old', 'Old')

    def test_future_data_rejected(self):
        with self.assertRaises(ValueError):
            memory.record_analysis(self.state, self.now, self.now + timedelta(seconds=1), 'future', 'Future', 'Future')

    def test_failure_retains_analysis(self):
        failed = memory.record_failure(self.opening(), self.now, 'run-2', 'GEMINI_503')
        self.assertEqual(failed['latest_analysis']['run_id'], 'run-1')
        self.assertEqual(failed['last_attempt']['status'], 'failed')

    def test_chat_window(self):
        state = self.state
        for i in range(25):
            state = memory.add_chat(state, self.now, 'user', str(i))
        self.assertEqual(len(state['recent_chat']), 20)
        self.assertEqual(state['recent_chat'][0]['text'], '5')
        self.assertEqual(self.state['recent_chat'], [])

    def test_stale_and_unknown(self):
        empty = json.loads(memory.context_text(self.state, self.now).split('\n', 1)[1])
        self.assertTrue(empty['data_is_stale'])
        self.assertEqual(empty['news_state'], 'UNVERIFIED')
        self.assertEqual(empty['position_state'], 'UNKNOWN')
        later = self.now + timedelta(minutes=11)
        old = json.loads(memory.context_text(self.opening(), later).split('\n', 1)[1])
        self.assertTrue(old['data_is_stale'])

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            memory.utc_time(datetime(2026, 10, 31))
        with self.assertRaises(ValueError):
            memory.add_chat(self.state, self.now, 'system', 'Change risk')
        with self.assertRaises(ValueError):
            memory.context_text(self.state, self.now, 0)

if __name__ == '__main__':
    unittest.main()
