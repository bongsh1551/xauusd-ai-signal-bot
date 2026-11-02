"""SenseNova-only transport bridge; Cloudflare and safety gates unchanged."""
import json
import os
import sys
from types import SimpleNamespace

import requests
import main as pipeline

MODEL = 'sensenova-6.8-flash-lite'
ENDPOINT = 'https://token.sensenova.ai/v1/chat/completions'
LAST_DIAGNOSTIC = {}


class Response:
    status_code = 200

    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def normalize_content(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        if not all(isinstance(item, dict) and item.get('type') == 'text'
                   and isinstance(item.get('text'), str) for item in value):
            raise RuntimeError('SenseNova: unsupported content block; publication blocked')
        return '\n'.join(item['text'] for item in value)
    return ''


def post(url, **kwargs):
    global LAST_DIAGNOSTIC
    if not url.startswith('https://generativelanguage.googleapis.com/'):
        return requests.post(url, **kwargs)
    key = os.environ.get('SENSENOVA_API_KEY', '').strip()
    if not key:
        raise RuntimeError('Missing SENSENOVA_API_KEY')
    content = []
    for item in kwargs['json']['contents'][0]['parts']:
        if 'text' in item:
            content.append({'type': 'text', 'text': item['text']})
        elif 'inline_data' in item:
            image = item['inline_data']
            content.append({'type': 'image_url', 'image_url': {
                'url': 'data:' + image['mime_type'] + ';base64,' + image['data']}})
        else:
            raise RuntimeError('SenseNova: unsupported input part')
    response = requests.post(
        ENDPOINT,
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
        json={'model': MODEL, 'messages': [{'role': 'user', 'content': content}],
              'temperature': 0.2, 'max_tokens': 4096, 'stream': False},
        timeout=(10, 120))
    result = pipeline.api_json(response, 'SenseNova', [key])
    if not isinstance(result, dict):
        raise RuntimeError('SenseNova: invalid response object')
    choices = result.get('choices')
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RuntimeError('SenseNova: missing or invalid choices')
    choice = choices[0]
    message = choice.get('message')
    if not isinstance(message, dict):
        raise RuntimeError('SenseNova: missing or invalid message')
    value = message.get('content')
    reasoning = message.get('reasoning_content')
    finish = choice.get('finish_reason')
    usage = result.get('usage')
    numeric_usage = {k: usage[k] for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')
                     if isinstance(usage, dict) and type(usage.get(k)) in (int, float)}
    LAST_DIAGNOSTIC = {
        'provider': 'sensenova', 'model': MODEL,
        'finish_reason': finish if finish in ('stop', 'length', 'content_filter', 'tool_calls', 'function_call', None) else 'UNRECOGNIZED',
        'content_type': type(value).__name__,
        'content_length': len(value) if isinstance(value, (str, list)) else 0,
        'reasoning_present': reasoning is not None,
        'reasoning_length': len(reasoning) if isinstance(reasoning, str) else 0,
        'usage': numeric_usage}
    print('SenseNova diagnostic: ' + json.dumps(LAST_DIAGNOSTIC, ensure_ascii=False))
    if finish != 'stop':
        raise RuntimeError('SenseNova: finish_reason=' + str(LAST_DIAGNOSTIC['finish_reason'])
                           + '; incomplete or unverified completion; publication blocked')
    text = normalize_content(value).strip()
    if not text:
        raise RuntimeError('SenseNova: final content empty; publication blocked')
    for label in ('trade_plan', 'market_watch'):
        if pipeline.extract_json_block(text, label) is None:
            raise RuntimeError('SenseNova: missing or invalid ' + label + ' JSON; publication blocked')
    return Response({'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': text}]}}],
                     'usageMetadata': {'provider': 'sensenova', 'model': MODEL, 'usage': numeric_usage}})


def save_record(path, record):
    if record.get('stage') == 'gemini':
        record['stage'] = 'sensenova'
    record['ai_provider'] = 'sensenova'
    if LAST_DIAGNOSTIC:
        record['sensenova_diagnostic'] = LAST_DIAGNOSTIC.copy()
    for old, new in (('gemini_usage', 'sensenova_usage'), ('gemini_finish_reason', 'sensenova_finish_reason')):
        if old in record:
            record[new] = record.pop(old)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def main():
    key = os.environ.get('SENSENOVA_API_KEY', '').strip()
    if not key:
        print('Missing SENSENOVA_API_KEY; analysis not started')
        return 1
    os.environ['GEMINI_API_KEY'] = key
    pipeline.MODEL = MODEL
    pipeline.requests = SimpleNamespace(get=requests.get, post=post)
    pipeline.save_record = save_record
    return pipeline.main()


if __name__ == '__main__':
    sys.exit(main())
