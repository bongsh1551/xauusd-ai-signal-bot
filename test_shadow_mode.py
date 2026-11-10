import unittest
import publication_guard

class PublicationGuardTests(unittest.TestCase):
    def chart(self, interval):
        return {"interval": interval, "timestamp_stale": False,
                "run_is_myt_weekend": False, "quality_review_required": False,
                "quality_verdict": "NO_NARROW_RUN_FLAG"}

    def record(self, **overrides):
        value = {"mode": "manual_signals",
                 "safety_gate": {"passed": True, "reasons": []},
                 "charts": [self.chart("5min"), self.chart("15min"), self.chart("1h")]}
        value.update(overrides)
        return value

    def test_verified_manual_record_passes(self):
        self.assertTrue(publication_guard.verified_record(self.record()))

    def test_shadow_mode_never_passes_live_publication_gate(self):
        self.assertFalse(publication_guard.verified_record(self.record(mode="shadow")))

    def test_missing_safety_reason_is_not_enough(self):
        self.assertFalse(publication_guard.verified_record(
            self.record(safety_gate={"passed": False, "reasons": []})))

    def test_missing_chart_blocks_publication(self):
        self.assertFalse(publication_guard.verified_record(
            self.record(charts=[self.chart("5min"), self.chart("15min")])))

    def test_stale_chart_blocks_publication(self):
        charts = [self.chart("5min"), self.chart("15min"), self.chart("1h")]
        charts[0]["timestamp_stale"] = True
        self.assertFalse(publication_guard.verified_record(self.record(charts=charts)))

if __name__ == "__main__":
    unittest.main()
