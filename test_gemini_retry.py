import unittest
from unittest.mock import patch

from sensenova_runner import gemini_post_with_retry


class FakeResponse:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class GeminiRetryTests(unittest.TestCase):
    def test_retries_503_then_returns_success(self):
        responses = [FakeResponse(503), FakeResponse(503), FakeResponse(200)]
        with patch("sensenova_runner.requests.post", side_effect=responses) as post, \
             patch("sensenova_runner.time.sleep") as sleep:
            result = gemini_post_with_retry("https://example.invalid", {})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(post.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_honors_retry_after_header_with_cap(self):
        responses = [FakeResponse(503, {"Retry-After": "4"}), FakeResponse(200)]
        with patch("sensenova_runner.requests.post", side_effect=responses), \
             patch("sensenova_runner.time.sleep") as sleep:
            gemini_post_with_retry("https://example.invalid", {})
        sleep.assert_called_once_with(4.0)

    def test_does_not_retry_non_transient_status(self):
        with patch("sensenova_runner.requests.post", return_value=FakeResponse(404)) as post, \
             patch("sensenova_runner.time.sleep") as sleep:
            result = gemini_post_with_retry("https://example.invalid", {})
        self.assertEqual(result.status_code, 404)
        post.assert_called_once()
        sleep.assert_not_called()

    def test_returns_final_503_after_retry_budget(self):
        with patch("sensenova_runner.requests.post", return_value=FakeResponse(503)) as post, \
             patch("sensenova_runner.time.sleep"):
            result = gemini_post_with_retry("https://example.invalid", {}, max_attempts=3)
        self.assertEqual(result.status_code, 503)
        self.assertEqual(post.call_count, 3)


if __name__ == "__main__":
    unittest.main()
