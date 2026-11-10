"""Safe SenseNova Instruct profile smoke test; never publishes or sends trading alerts."""
import json
import os
import sys
import requests

MODEL = "sensenova-6.8-flash-lite"
ENDPOINT = "https://token.sensenova.ai/v1/chat/completions"

def main():
    key = os.environ.get("SENSENOVA_API_KEY", "").strip()
    if not key:
        print("ERROR: SENSENOVA_API_KEY is not configured")
        return 2

    prompt = """You are validating a market-analysis response format, not issuing a live trading signal.
Use only this synthetic sample:
H1: lower high sequence, bearish context.
M15: price retraced into a previously identified supply zone 2388.0-2390.0.
M5: last closed candle swept 2389.2, rejected, and closed at 2387.6; the next candle has not closed.
Return concise Chinese with exactly one status line using WAIT / APPROACH / CONFIRMED, then a market_watch JSON code block with zones array. Because the next candle is not closed, do not claim entry confirmation and do not output trade_plan. Do not invent any additional prices."""

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        # SenseNova 6.8 documented Instruct (non-thinking) Reasoning profile.
        "temperature": 1.0,
        "top_p": 1.0,
        "top_k": 40,
        "min_p": 0.0,
        "presence_penalty": 2.0,
        "repetition_penalty": 1.0,
        "max_tokens": 8192,
        "stream": False,
    }
    response = requests.post(
        ENDPOINT,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        json=payload,
        timeout=(10, 120),
        allow_redirects=False,
    )
    print("HTTP_STATUS=" + str(response.status_code))
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        print("ERROR: response has no valid choices")
        return 3
    choice = choices[0]
    message = choice.get("message") or {}
    content = message.get("content") or ""
    usage = data.get("usage") or {}
    result = {
        "model": data.get("model", MODEL),
        "finish_reason": choice.get("finish_reason"),
        "content_length": len(content) if isinstance(content, str) else 0,
        "content_present": bool(content),
        "reasoning_length": len(message.get("reasoning") or "") if isinstance(message.get("reasoning"), str) else None,
        "usage": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens") if usage.get(k) is not None},
    }
    print("SENSENOVA_TEST_RESULT=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
    # Output is intentionally not forwarded to Telegram or Cloudflare.
    if choice.get("finish_reason") != "stop" or not isinstance(content, str) or not content.strip():
        print("RESULT=FAIL_INCOMPLETE_MODEL_OUTPUT")
        return 4
    print("RESULT=PASS_RESPONSE_COMPLETE_NO_PUBLICATION")
    return 0

if __name__ == "__main__":
    sys.exit(main())
