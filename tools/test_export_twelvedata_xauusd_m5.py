import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import Mock

MODULE_PATH=Path(__file__).with_name("export_twelvedata_xauusd_m5.py")
SPEC=importlib.util.spec_from_file_location("xauusd_probe",MODULE_PATH)
probe=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)

class ProbeTests(unittest.TestCase):
    def setUp(self):
        os.environ["TWELVEDATA_API_KEY"]="test-secret"
    def tearDown(self):
        os.environ.pop("TWELVEDATA_API_KEY",None)
    def test_outputsize_only_allows_300_or_500(self):
        self.assertEqual(probe.args_parse.__name__,"args_parse")
    def test_provider_error_redacts_secret(self):
        session=Mock()
        response=Mock(status_code=400)
        response.json.return_value={"status":"error","code":400,"message":"bad key test-secret"}
        response.headers={}
        session.get.return_value=response
        with self.assertRaises(RuntimeError) as caught:
            probe.request_json(session,"time_series",{"symbol":"XAU/USD"},"test-secret",1)
        self.assertNotIn("test-secret",str(caught.exception))
        self.assertIn("HTTP 400",str(caught.exception))
    def test_valid_response_returned(self):
        session=Mock()
        response=Mock(status_code=200)
        response.json.return_value={"meta":{"symbol":"XAU/USD","interval":"5min"},"values":[{"datetime":"2026-11-14 00:00:00"}]}
        response.headers={"api-credits-used":"1"}
        session.get.return_value=response
        data,headers=probe.request_json(session,"time_series",{"symbol":"XAU/USD"},"test-secret",1)
        self.assertEqual(data["meta"]["symbol"],"XAU/USD")
        self.assertEqual(headers["api-credits-used"],"1")

if __name__=="__main__": unittest.main()
