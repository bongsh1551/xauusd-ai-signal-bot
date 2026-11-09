"""SenseNova-only transport: three attempts, five seconds between retries."""
import json
import time
from types import SimpleNamespace
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
import requests
from requests.adapters import HTTPAdapter

MAX_ATTEMPTS = 3
RETRY_SECONDS = 5
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

class SenseNovaRequestFailed(RuntimeError):
    pass

def error_types(exc):
    seen, names, pending = set(), [], [exc]
    while pending and len(seen) < 12:
        item = pending.pop(0)
        if not isinstance(item, BaseException) or id(item) in seen:
            continue
        seen.add(id(item))
        names.append(type(item).__name__)
        pending.extend([item.__cause__, item.__context__, getattr(item, 'reason', None)])
        pending.extend(x for x in item.args if isinstance(x, BaseException))
    return list(dict.fromkeys(names))

def payload_diagnostics(payload):
    size = len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    images = chars = messages = 0
    for message in payload.get('messages', []) if isinstance(payload, dict) else []:
        messages += 1
        content = message.get('content', []) if isinstance(message, dict) else []
        for part in content if isinstance(content, list) else []:
            if isinstance(part, dict) and part.get('type') == 'image_url':
                images += 1
                image = part.get('image_url', {})
                value = image.get('url', '') if isinstance(image, dict) else ''
                if isinstance(value, str) and value.startswith('data:'):
                    chars += len(value.partition(',')[2])
    return dict(request_json_bytes=size, image_count=images,
                image_base64_chars=chars, message_count=messages)

def retry_after_seconds(response):
    value = response.headers.get('Retry-After')
    if value is None:
        return 0.0
    try:
        return max(0.0, float(value))
    except (ValueError, TypeError):
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            return max(0.0, (when-datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0.0

def disabled_fallback(*args, **kwargs):
    raise SenseNovaRequestFailed('Gemini fallback disabled by SenseNova-only policy')

def request_with_retry(session, url, options, sleep=None):
    sleep = time.sleep if sleep is None else sleep
    diagnostics = payload_diagnostics(options.get('json', {}))
    started = time.monotonic()
    for attempt in range(1, MAX_ATTEMPTS+1):
        response, retryable, failure, error_chain = None, False, None, []
        try:
            response = session.post(url, **options)
        except (requests.exceptions.SSLError, requests.exceptions.ProxyError) as exc:
            failure, error_chain = type(exc).__name__, error_types(exc)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            retryable, failure, error_chain = True, type(exc).__name__, error_types(exc)
        except requests.exceptions.RequestException as exc:
            failure, error_chain = type(exc).__name__, error_types(exc)
        if response is not None:
            status = response.status_code
            if 200 <= status < 300:
                print(json.dumps(dict(event='sensenova_request_success', attempt=attempt,
                    max_attempts=MAX_ATTEMPTS, http_status=status, **diagnostics), sort_keys=True))
                return response
            retryable, failure = status in RETRYABLE_STATUS, 'HTTP_'+str(status)
            if retry_after_seconds(response) > RETRY_SECONDS:
                retryable = False
                failure += '_RETRY_AFTER_EXCEEDS_POLICY'
            response.close()
        will_retry = retryable and attempt < MAX_ATTEMPTS
        print(json.dumps(dict(event='sensenova_request_error', attempt=attempt,
            max_attempts=MAX_ATTEMPTS, failure=failure, will_retry=will_retry,
            delay_seconds=RETRY_SECONDS if will_retry else 0,
            error_chain=error_chain,
            elapsed_ms=round((time.monotonic()-started)*1000, 1), **diagnostics), sort_keys=True))
        if not will_retry:
            raise SenseNovaRequestFailed('SenseNova request failed: '+str(failure)
                +'; attempts='+str(attempt)+'; fallback disabled') from None
        sleep(RETRY_SECONDS)
    raise AssertionError('Unreachable retry state')

def install(runner):
    if getattr(runner, '_safe_transport_installed', False):
        return
    original_post = requests.post
    session = requests.Session()
    session.mount('https://', HTTPAdapter(max_retries=0))
    runner.gemini_post_with_retry = disabled_fallback
    def post(url, **kwargs):
        if url.startswith('https://generativelanguage.googleapis.com/'):
            return disabled_fallback()
        if url != runner.ENDPOINT:
            return original_post(url, **kwargs)
        options = dict(kwargs)
        options['allow_redirects'] = False
        options.setdefault('timeout', (10, 120))
        return request_with_retry(session, url, options)
    runner.requests = SimpleNamespace(get=requests.get, post=post)
    runner._safe_transport_installed = True
