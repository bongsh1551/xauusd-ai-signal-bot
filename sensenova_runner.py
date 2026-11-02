"""SenseNova transport bridge for the existing analysis pipeline.

Legacy Gemini-shaped fields are retained for compatibility, but no request
is sent to Google. Cloudflare deployment and safety gates are unchanged.
"""
import json
import os
import sys
from types import SimpleNamespace

import requests
import main as pipeline

MODEL = 'sensenova-6.8-flash-lite'
ENDPOINT = 'https://token.sensenova.ai/v1/chat/completions'


class Response:
    status_code = 200

    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def post(url, **kwargs):
    if not url.startswith('https://generativelanguage.googleapis.com/'):
        return requests.post(url, **kwargs)
    key = os.environ.get('SENSENOVA_API_KEY', '').strip()
    if not key:
        raise RuntimeError('Missing SENSENOVA_API_KEY')
    original = kwargs['json']
    content = []
    for item in original['contents'][0]['parts']:
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
    choices = result.get('choices') or []
    if not choices:
        raise RuntimeError('SenseNova: no choices')
    choice = choices[0]
    text = (choice.get('message') or {}).get('content')
    if not isinstance(text, str) or not text.strip() or choice.get('finish_reason') != 'stop':
        raise RuntimeError('SenseNova: missing or incomplete output; publication blocked')
    if pipeline.extract_json_block(text, 'trade_plan') is None:
        raise RuntimeError('SenseNova: missing or invalid trade_plan JSON; publication blocked')
    if pipeline.extract_json_block(text, 'market_watch') is None:
        raise RuntimeError('SenseNova: missing or invalid market_watch JSON; publication blocked')
    return Response({'candidates': [{'finishReason': 'STOP',
                     'content': {'parts': [{'text': text}]}}],
                     'usageMetadata': {'provider': 'sensenova', 'model': MODEL,
                                       'usage': result.get('usage', {})}})


def save_record(path, record):
    if record.get('stage') == 'gemini':
        record['stage'] = 'sensenova'
    record['ai_provider'] = 'sensenova'
    if 'gemini_usage' in record:
        record['sensenova_usage'] = record.pop('gemini_usage')
    if 'gemini_finish_reason' in record:
        record['sensenova_finish_reason'] = record.pop('gemini_finish_reason')
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def main():
    key = os.environ.get('SENSENOVA_API_KEY', '').strip()
    if not key:
        print('Missing SENSENOVA_API_KEY; analysis not started')
        return 1
    # Satisfy the legacy configuration slot without loading a Google key.
    os.environ['GEMINI_API_KEY'] = key
    pipeline.MODEL = MODEL
    pipeline.requests = SimpleNamespace(get=requests.get, post=post)
    pipeline.save_record = save_record
    return pipeline.main()


if __name__ == '__main__':
    sys.exit(main())
