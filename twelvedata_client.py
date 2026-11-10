"""Twelve Data requests with authorized primary/backup key failover and bounded 429 retry."""
import time
import requests


def get(url, *, params=None, timeout=(10, 30), api_keys=None, sleep=None):
    """Use configured authorized keys in order; switch on 429, retry the last key once."""
    if sleep is None:
        sleep = time.sleep
    base_params = dict(params or {})
    keys = [str(key).strip() for key in (api_keys or []) if str(key).strip()]
    if not keys:
        # Backward-compatible path for callers that supply apikey in params.
        response = requests.get(url, params=base_params, timeout=timeout)
        if response.status_code != 429:
            return response
        keys = [base_params.pop('apikey', '')]
        if not keys[0]:
            return response

    response = None
    for index, key in enumerate(keys):
        request_params = dict(base_params)
        request_params['apikey'] = key
        slot = 'PRIMARY' if index == 0 else f'BACKUP_{index}'
        response = requests.get(url, params=request_params, timeout=timeout)
        if response.status_code != 429:
            print(f'Twelve Data request completed using {slot} key.')
            return response
        if index < len(keys) - 1:
            print(f'Twelve Data HTTP 429 on {slot}; switching to configured authorized backup key.')
            continue

        raw_retry_after = response.headers.get('Retry-After', '')
        try:
            wait_seconds = max(1, min(int(raw_retry_after), 120))
        except (TypeError, ValueError):
            wait_seconds = 60
        print(f'Twelve Data HTTP 429 on {slot}; waiting {wait_seconds}s before one retry.')
        sleep(wait_seconds)
        response = requests.get(url, params=request_params, timeout=timeout)
        print(f'Twelve Data retry completed with {slot} key; HTTP {response.status_code}.')
        return response
    return response
