"""Small, bounded retry policy for Twelve Data rate-limit responses."""
import time
import requests


def get(url, *, params=None, timeout=(10, 30), sleep=time.sleep):
    """Retry one HTTP 429 after Retry-After; never rotate API keys or bypass quotas."""
    response = requests.get(url, params=params, timeout=timeout)
    if response.status_code != 429:
        return response
    raw_retry_after = response.headers.get('Retry-After', '')
    try:
        wait_seconds = max(1, min(int(raw_retry_after), 120))
    except (TypeError, ValueError):
        wait_seconds = 60
    print(f'Twelve Data HTTP 429; waiting {wait_seconds}s before one retry with the same API key.')
    sleep(wait_seconds)
    return requests.get(url, params=params, timeout=timeout)
