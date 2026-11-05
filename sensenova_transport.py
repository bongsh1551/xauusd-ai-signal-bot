"""Retry connection establishment and log safe payload/latency diagnostics only."""
import json
import time
from types import SimpleNamespace
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def error_types(exc):
    seen = set()
    names = []
    pending = [exc]
    while pending and len(seen) < 12:
        item = pending.pop(0)
        if not isinstance(item, BaseException) or id(item) in seen:
            continue
        seen.add(id(item))
        names.append(type(item).__name__)
        pending.extend([item.__cause__, item.__context__, getattr(item, 'reason', None)])
        pending.extend(x for x in item.args if isinstance(x, BaseException))
    return sorted(set(names))


def payload_diagnostics(payload):
    """Return sizes/counts only; never return prompt text, image data, or credentials."""
    encoded_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    image_data_chars = 0
    image_count = 0
    message_count = 0
    for message in payload.get('messages', []) if isinstance(payload, dict) else []:
        message_count += 1
        content = message.get('content', []) if isinstance(message, dict) else []
        for part in content if isinstance(content, list) else []:
            if isinstance(part, dict) and part.get('type') == 'image_url':
                image_count += 1
                image_url = part.get('image_url', {})
                value = image_url.get('url', '') if isinstance(image_url, dict) else ''
                if isinstance(value, str) and value.startswith('data:'):
                    image_data_chars += len(value.partition(',')[2])
    return {
        'request_json_bytes': encoded_bytes,
        'image_count': image_count,
        'image_base64_chars': image_data_chars,
        'message_count': message_count,
    }


def install(runner):
    if getattr(runner, '_safe_transport_installed', False):
        return
    original_post = requests.post
    session = requests.Session()
    retry = Retry(total=2, connect=2, read=0, status=0, other=0,
                  redirect=0, backoff_factor=0.5,
                  allowed_methods=frozenset({'POST'}))
    session.mount('https://', HTTPAdapter(max_retries=retry))

    def post(url, **kwargs):
        if url != runner.ENDPOINT:
            return original_post(url, **kwargs)
        options = dict(kwargs)
        options['allow_redirects'] = False
        options.setdefault('timeout', (10, 120))
        diagnostics = payload_diagnostics(options.get('json', {}))
        started = time.perf_counter()
        try:
            response = session.post(url, **options)
        except requests.exceptions.RequestException as exc:
            names = error_types(exc)
            diagnostic = {
                'event': 'sensenova_transport_error',
                **diagnostics,
                'elapsed_ms': round((time.perf_counter() - started) * 1000, 1),
                'timeout_seconds': list(options.get('timeout', ())),
                'exception_types': names,
                'connect_retries_max': 2,
                'read_retries': 0,
                'http_status_retries': 0,
            }
            print(json.dumps(diagnostic, sort_keys=True))
            raise RuntimeError('SenseNova transport failure: ' + ','.join(names)) from None
        print(json.dumps({
            'event': 'sensenova_transport_response',
            **diagnostics,
            'elapsed_ms': round((time.perf_counter() - started) * 1000, 1),
            'http_status': response.status_code,
        }, sort_keys=True))
        return response

    runner.requests = SimpleNamespace(get=requests.get, post=post)
    runner._safe_transport_installed = True
