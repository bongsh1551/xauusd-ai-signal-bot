import importlib.util
import os
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

MODULE_PATH = Path(__file__).with_name("export_twelvedata_xauusd_m5.py")
SPEC = importlib.util.spec_from_file_location("xauusd_exporter", MODULE_PATH)
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


class ExporterTests(unittest.TestCase):
    def setUp(self):
        exporter.API_CALLS_USED = 0
        exporter.API_CALLS_CAP = 10
        os.environ["TWELVEDATA_API_KEY"] = "test-secret"

    def tearDown(self):
        os.environ.pop("TWELVEDATA_API_KEY", None)

    def test_fetch_uses_xauusd_m5_and_utc_range(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "meta": {"symbol": "XAU/USD", "interval": "5min"},
            "values": [{"datetime": "2026-11-01 00:00:00", "open": "1", "high": "2", "low": "0.5", "close": "1.5"}]
        }
        session = Mock()
        session.get.return_value = response
        values, meta = exporter.fetch(session, "test-secret", date(2026, 11, 1), date(2026, 11, 7), 1)
        self.assertEqual(len(values), 1)
        self.assertEqual(meta["interval"], "5min")
        kwargs = session.get.call_args.kwargs
        self.assertEqual(kwargs["params"]["symbol"], "XAU/USD")
        self.assertEqual(kwargs["params"]["interval"], "5min")
        self.assertEqual(kwargs["params"]["timezone"], "UTC")
        self.assertEqual(kwargs["params"]["apikey"], "test-secret")
        self.assertEqual(exporter.API_CALLS_USED, 1)

    def test_wrong_symbol_metadata_is_rejected(self):
        response = Mock(status_code=200)
        response.json.return_value = {"meta": {"symbol": "EUR/USD", "interval": "5min"}, "values": []}
        session = Mock()
        session.get.return_value = response
        with self.assertRaisesRegex(RuntimeError, "unexpected symbol/interval"):
            exporter.fetch(session, "test-secret", date(2026, 11, 1), date(2026, 11, 7), 1)

    def test_api_call_cap_stops_before_request(self):
        exporter.API_CALLS_CAP = 0
        session = Mock()
        with self.assertRaisesRegex(RuntimeError, "safety cap"):
            exporter.fetch(session, "test-secret", date(2026, 11, 1), date(2026, 11, 7), 1)
        session.get.assert_not_called()

    def test_provider_error_does_not_leak_key(self):
        response = Mock(status_code=200)
        response.json.return_value = {"status": "error", "code": 401, "message": "invalid key test-secret"}
        session = Mock()
        session.get.return_value = response
        with self.assertRaises(RuntimeError) as caught:
            exporter.fetch(session, "test-secret", date(2026, 11, 1), date(2026, 11, 7), 1)
        self.assertNotIn("test-secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
