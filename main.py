import os
import sys

import requests

MODEL = 'gemini-3.5-flash-lite'

def main():
    if os.getenv('GITHUB_EVENT_NAME') != 'workflow_dispatch':
        print('测试阶段：跳过定时任务，请手动运行。')
        return

    names = ['GEMINI_API_KEY', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID']
    config = {name: os.getenv(name, '').strip() for name in names}
    missing = [name for name in names if not config[name]]
    if missing:
        print('缺少配置：' + ', '.join(missing))
        sys.exit(1)

    try:
        response = requests.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent',
            headers={'x-goog-api-key': config['GEMINI_API_KEY']},
            json={
                'contents': [{'parts': [{'text': 'Connectivity test only. Reply exactly: GOLD_SCALP_OK'}]}],
                'generationConfig': {'maxOutputTokens': 128},
            },
            timeout=(10, 90),
        )
        if response.status_code != 200:
            print(f'Gemini 请求失败，HTTP {response.status_code}；停止测试，不自动重试或切换付费服务。')
            sys.exit(1)
        data = response.json()
        candidates = data.get('candidates', [])
        parts = candidates[0].get('content', {}).get('parts', []) if candidates else []
        reply = ''.join(part.get('text', '') for part in parts if not part.get('thought')).strip()
        if reply != 'GOLD_SCALP_OK':
            print('Gemini 返回内容未通过测试校验；未生成交易信号。')
            sys.exit(1)
    except (requests.RequestException, ValueError, KeyError, TypeError):
        print('Gemini 网络或响应解析失败；未输出密钥或完整响应。')
        sys.exit(1)

    message = (
        '✅ GoldScalp AI：Gemini 连线测试成功！\n\n'
        f'模型：{MODEL}\n'
        'GitHub Actions → Gemini → Telegram 已接通。\n'
        '本次仅测试文字响应，尚未测试看图或行情分析。\n'
        '这不是交易信号，没有执行任何下单操作。'
    )
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{config['TELEGRAM_BOT_TOKEN']}/sendMessage",
            json={'chat_id': config['TELEGRAM_CHAT_ID'], 'text': message},
            timeout=30,
        )
        result = response.json()
        if response.status_code != 200 or not result.get('ok'):
            print(f'Telegram 发送失败，HTTP {response.status_code}。')
            sys.exit(1)
    except (requests.RequestException, ValueError):
        print('Telegram 网络或响应解析失败。')
        sys.exit(1)
    print('Gemini 连线与 Telegram 通知测试成功。')

if __name__ == '__main__':
    main()
