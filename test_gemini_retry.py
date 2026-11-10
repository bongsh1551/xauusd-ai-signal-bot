import unittest
from sensenova_runner import gemini_post_with_retry

class GeminiFallbackDisabledTests(unittest.TestCase):
    def test_legacy_gemini_transport_is_disabled(self):
        with self.assertRaisesRegex(RuntimeError, "Gemini fallback disabled"):
            gemini_post_with_retry("https://example.invalid", {})

if __name__ == "__main__":
    unittest.main()
