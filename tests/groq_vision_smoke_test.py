"""Groq Qwen vision connectivity test; synthetic images only, no market data or publication."""
import base64
import json
import os
import sys
import requests

MODEL = "qwen/qwen3.8-27b"
ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

# A tiny valid PNG; repeated three times to verify the production image-count shape.
PNG_1X1 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAwMCAO+jV3sAAAAASUVORK5CYII="
)

def main():
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        print("ERROR: GROQ_API_KEY is not configured in GitHub Actions secrets")
        return 2

    content = [{"type": "text", "text":
        "This is a connectivity test only. Three synthetic 1x1 images are attached. "
        "Reply exactly: GROQ_VISION_OK. Do not infer anything about markets."}]
    for _ in range(3):
        content.append({"type": "image_url", "image_url": {
            "url": "data:image/png;base64," + PNG_1X1
        }})

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.2,
        "max_completion_tokens": 128,
        "stream": False,
    }
    response = requests.post(
        ENDPOINT,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        json=payload,
        timeout=(10, 90),
        allow_redirects=False,
    )
    print("HTTP_STATUS=" + str(response.status_code))
    if response.status_code >= 400:
        # Do not print request headers or API key.
        try:
            detail = response.json()
            error = detail.get("error", {})
            print("GROQ_ERROR=" + json.dumps({
                "type": error.get("type"),
                "code": error.get("code"),
                "message": str(error.get("message", ""))[:500],
            }, ensure_ascii=False))
        except Exception:
            print("GROQ_ERROR=non-JSON error response")
        response.raise_for_status()

    data = response.json()
    choices = data.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        print("ERROR: response has no valid choices")
        return 3
    choice = choices[0]
    message = choice.get("message") or {}
    output = message.get("content") or ""
    usage = data.get("usage") or {}
    summary = {
        "model": data.get("model", MODEL),
        "finish_reason": choice.get("finish_reason"),
        "content_length": len(output) if isinstance(output, str) else 0,
        "content_present": bool(output),
        "usage": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens") if usage.get(k) is not None},
        "image_count": 3,
    }
    print("GROQ_TEST_RESULT=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    if choice.get("finish_reason") != "stop" or not isinstance(output, str) or "GROQ_VISION_OK" not in output:
        print("RESULT=FAIL_INCOMPLETE_OR_UNEXPECTED_MODEL_OUTPUT")
        return 4
    print("RESULT=PASS_GROQ_VISION_3_IMAGES_NO_PUBLICATION")
    return 0

if __name__ == "__main__":
    sys.exit(main())
