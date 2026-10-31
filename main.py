import base64
import io
import json
import os
import sys
from datetime import datetime, timezone

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
import requests


PROMPT_PATH = 'prompts/scalper.txt'
GEMINI_URL = (
    'https://generativelanguage.googleapis.com/v1beta/models/'
    'gemini-2.5-flash:generateContent'
)


def load_prompt():
    with open(PROMPT_PATH, 'r', encoding='utf-8') as handle:
        prompt = handle.read().strip()
    if not prompt:
        raise RuntimeError('prompt file is empty')
    return prompt


def fetch_chart(key, interval, minutes, now):
    response = requests.get(
        'https://api.twelvedata.com/time_series',
        params={'symbol': 'XAU/USD', 'interval': interval,
                'outputsize': 160, 'timezone': 'UTC', 'apikey': key},
        timeout=(10, 45),
    )
    if response.status_code != 200:
        raise RuntimeError(f'{interval}: data HTTP {response.status_code}')
    data = response.json()
    if data.get('status') != 'ok' or not data.get('values'):
        raise RuntimeError(f'{interval}: data rejected; code={data.get("code", "unknown")}')
    meta = data.get('meta', {})
    if meta.get('symbol') != 'XAU/USD' or meta.get('interval') != interval:
        raise RuntimeError(f'{interval}: unexpected symbol or interval')
    frame = pd.DataFrame(data['values'])
    frame.index = pd.to_datetime(frame.pop('datetime'), utc=True, errors='raise')
    if frame.index.has_duplicates or frame.index.isna().any():
        raise RuntimeError(f'{interval}: invalid or duplicate timestamps')
    frame = frame[['open', 'high', 'low', 'close']].apply(pd.to_numeric, errors='raise')
    frame.columns = ['Open', 'High', 'Low', 'Close']
    frame = frame.sort_index()
    if not frame.map(lambda x: pd.notna(x) and 0 < x < float('inf')).all().all():
        raise RuntimeError(f'{interval}: invalid prices')
    if ((frame.High < frame[['Open', 'Close', 'Low']].max(axis=1)) |
            (frame.Low > frame[['Open', 'Close', 'High']].min(axis=1))).any():
        raise RuntimeError(f'{interval}: invalid OHLC ordering')
    if frame.index.max() > now + pd.Timedelta(seconds=60):
        raise RuntimeError(f'{interval}: future timestamp; stop for timezone verification')
    frame = frame[frame.index + pd.Timedelta(minutes=minutes) <= now]
    if len(frame) < 50:
        raise RuntimeError(f'{interval}: insufficient closed candles')
    last_open = frame.index[-1]
    age = (now - (last_open + pd.Timedelta(minutes=minutes))).total_seconds() / 60
    stale = age > max(15, minutes * 2)
    label = 'HISTORICAL / STALE - TEST ONLY' if stale else 'CHART TEST ONLY - NOT A SIGNAL'
    plot_frame = frame.tail(120).copy()
    plot_frame.index = plot_frame.index.tz_convert('Asia/Kuala_Lumpur').tz_localize(None)
    buffer = io.BytesIO()
    fig, _ = mpf.plot(
        plot_frame, type='candle', style='yahoo', volume=False,
        title=f'XAU/USD {interval} | MYT UTC+8\n{label}',
        ylabel='USD per oz', datetime_format='%m-%d %H:%M',
        figsize=(14, 7), returnfig=True, tight_layout=True,
    )
    try:
        fig.savefig(buffer, format='png', dpi=130, bbox_inches='tight')
    finally:
        plt.close(fig)
    buffer.seek(0)
    last_myt = last_open.tz_convert('Asia/Kuala_Lumpur').strftime('%Y-%m-%d %H:%M')
    gaps = int((frame.index.to_series().diff() > pd.Timedelta(minutes=minutes)).sum())
    caption = (
        f'🧪 XAU/USD {interval} 画图测试\n'
        f'最后已收线 K 线起点（大马时间）：{last_myt}\n'
        f'距该根收线：{age:.1f} 分钟\n'
        f'数据状态：{"历史/陈旧数据，仅作画图测试" if stale else "通过本次时间阈值检查，未验证实时报价"}\n'
        f'样本内时间缺口：{gaps}（可能含休市，尚未判定原因）\n'
        '来源：Twelve Data；不等于你的券商报价。\n'
        '本图仅测试，不是交易信号；未调用 AI，禁止据此入场。'
    )
    metadata = {
        'interval': interval,
        'candles_available': int(len(frame)),
        'candles_sent': int(min(40, len(frame))),
        'last_closed_candle_utc': last_open.isoformat(),
        'last_closed_candle_myt': last_myt,
        'minutes_since_close': round(age, 1),
        'historical_or_stale': bool(stale),
        'time_gaps_in_sample': gaps,
    }
    return interval, buffer, caption, frame, metadata


def build_ohlc_text(frame, interval, candles=40):
    recent = frame.tail(candles)
    lines = [f'{interval} OHLC（UTC，已收线，最多 {candles} 根）：']
    for timestamp, row in recent.iterrows():
        lines.append(
            f'{timestamp.isoformat()} O={row.Open:.2f} H={row.High:.2f} '
            f'L={row.Low:.2f} C={row.Close:.2f}'
        )
    return '\n'.join(lines)


def call_gemini(api_key, prompt, charts):
    parts = [{
        'text': (
            f'{prompt}\n\n'
            '【执行模式】历史行情分析测试。今天是周末，数据可能来自最近交易日，'
            '不是实时市场。必须以“🧪 历史行情分析测试｜不是当前交易信号，不可据此进场”开头。\n\n'
            '【当前时间】UTC：'
            f'{datetime.now(timezone.utc).isoformat()}\n'
            '请只依据以下图像和 OHLC 分析；不要使用未提供的新闻或宏观资料。\n\n'
        )
    }]
    for interval, image, _caption, frame, _metadata in charts:
        parts.append({'text': build_ohlc_text(frame, interval)})
        parts.append({
            'inline_data': {
                'mime_type': 'image/png',
                'data': base64.b64encode(image.getvalue()).decode('ascii'),
            }
        })
    payload = {
        'contents': [{'role': 'user', 'parts': parts}],
        'generationConfig': {'temperature': 0.2, 'maxOutputTokens': 2048},
    }
    response = requests.post(
        GEMINI_URL,
        params={'key': api_key},
        headers={'Content-Type': 'application/json'},
        json=payload,
        timeout=(10, 120),
    )
    if response.status_code != 200:
        raise RuntimeError(f'Gemini HTTP {response.status_code}')
    result = response.json()
    try:
        text = result['candidates'][0]['content']['parts'][0]['text'].strip()
    except (KeyError, IndexError, TypeError):
        raise RuntimeError('Gemini returned no usable analysis text')
    if not text:
        raise RuntimeError('Gemini returned empty analysis')
    return text, result


def send_telegram(token, chat_id, text):
    message = text[:4000]
    response = requests.post(
        f'https://api.telegram.org/bot{token}/sendMessage',
        data={'chat_id': chat_id, 'text': message},
        timeout=(10, 60),
    )
    ok = response.status_code == 200 and response.json().get('ok') is True
    if not ok:
        raise RuntimeError(f'Telegram sendMessage failed: HTTP {response.status_code}')
    return {'sent': True, 'characters_sent': len(message), 'truncated': len(text) > 4000}


def write_journal(charts, prompt, analysis, gemini_result, telegram_result):
    os.makedirs('journal', exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    record = {
        'run_id': run_id,
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'mode': 'historical_weekend_test',
        'prompt_path': PROMPT_PATH,
        'prompt_sha256': __import__('hashlib').sha256(
            prompt.encode('utf-8')).hexdigest(),
        'data_source': 'Twelve Data',
        'ai_model': 'gemini-2.5-flash',
        'charts': [metadata for _i, _image, _caption, _frame, metadata in charts],
        'ai_raw_output': analysis,
        'gemini_usage': gemini_result.get('usageMetadata', {}),
        'telegram': telegram_result,
        'execution': 'manual_only_no_auto_trading',
    }
    path = f'journal/{run_id}.json'
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
    return path


def main():
    if os.getenv('GITHUB_EVENT_NAME') != 'workflow_dispatch':
        print('测试阶段：跳过定时任务。')
        return
    names = [
        'TWELVEDATA_API_KEY', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID',
        'GEMINI_API_KEY',
    ]
    config = {name: os.getenv(name, '').strip() for name in names}
    missing = [name for name in names if not config[name]]
    if missing:
        print(f'缺少必要 Secret：{", ".join(missing)}')
        sys.exit(1)
    try:
        prompt = load_prompt()
        now = pd.Timestamp.now(tz='UTC')
        charts = [
            fetch_chart(config['TWELVEDATA_API_KEY'], interval, minutes, now)
            for interval, minutes in [('5min', 5), ('15min', 15), ('1h', 60)]
        ]
        analysis, gemini_result = call_gemini(
            config['GEMINI_API_KEY'], prompt, charts
        )
        telegram_result = send_telegram(
            config['TELEGRAM_BOT_TOKEN'], config['TELEGRAM_CHAT_ID'], analysis
        )
        journal_path = write_journal(
            charts, prompt, analysis, gemini_result, telegram_result
        )
        for _interval, image, _caption, _frame, _metadata in charts:
            image.close()
        print(f'历史测试分析已发送；Journal：{journal_path}')
    except RuntimeError as exc:
        print(str(exc))
        sys.exit(1)
    except Exception as exc:
        print(f'测试停止：{type(exc).__name__}；为保护密钥不输出原始请求或响应。')
        sys.exit(1)


if __name__ == '__main__':
    main()
