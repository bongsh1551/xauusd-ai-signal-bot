import unittest

import pandas as pd

from main import candle_range_quality, requires_candle_quality_review


def frame(ranges):
    return pd.DataFrame({
        "High": [100.0 + value for value in ranges],
        "Low": [100.0 for _ in ranges],
    })


class CandleQualityTests(unittest.TestCase):
    def test_h1_sample_with_28_near_flat_bars_is_flagged(self):
        stats = candle_range_quality(frame([0.25] * 28 + [1.0] * 12), 0.30)
        self.assertEqual(stats["count"], 28)
        self.assertEqual(stats["longest_run"], 28)
        self.assertTrue(requires_candle_quality_review(stats))

    def test_m15_chart_window_flat_run_is_flagged_even_if_recent_sample_active(self):
        chart = candle_range_quality(frame([0.20] * 74 + [1.0] * 46), 0.30)
        recent = candle_range_quality(frame([1.0] * 40), 0.30)
        self.assertTrue(requires_candle_quality_review(chart, recent))
        self.assertEqual(recent["count"], 0)

    def test_normal_active_candles_are_not_flagged(self):
        stats = candle_range_quality(frame([0.8, 1.1, 0.6, 1.4] * 10), 0.30)
        self.assertFalse(requires_candle_quality_review(stats))

    def test_isolated_narrow_candles_are_not_flagged(self):
        stats = candle_range_quality(frame([0.1, 1.0, 0.1, 1.0] * 10), 0.30)
        self.assertFalse(requires_candle_quality_review(stats))

    def test_empty_sample_is_safe(self):
        stats = candle_range_quality(frame([]), 0.30)
        self.assertEqual(stats, {"count": 0, "ratio": 0.0, "longest_run": 0})
        self.assertFalse(requires_candle_quality_review(stats))


if __name__ == "__main__":
    unittest.main()
