import json
import unittest

from sensenova_transport import payload_diagnostics


class SenseNovaPayloadDiagnosticsTests(unittest.TestCase):
    def test_reports_payload_and_image_sizes_without_exposing_content(self):
        payload = {
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "private prompt"},
                    {"type": "image_url", "image_url": {
                        "url": "data:image/png;base64,QUJDREVGRw=="
                    }},
                    {"type": "image_url", "image_url": {
                        "url": "data:image/png;base64,SElKS0w="
                    }},
                ],
            }],
        }
        result = payload_diagnostics(payload)
        expected_bytes = len(json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8"))
        self.assertEqual(result["request_json_bytes"], expected_bytes)
        self.assertEqual(result["image_count"], 2)
        self.assertEqual(result["image_base64_chars"], 16)
        self.assertEqual(result["message_count"], 1)
        self.assertNotIn("private prompt", json.dumps(result))
        self.assertNotIn("QUJDREVGRw==", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
