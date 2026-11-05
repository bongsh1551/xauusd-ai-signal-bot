import base64
import hashlib
import io
import json
import os
import re
import sys
import uuid
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
import requests

from fundamentals import collect_fundamentals

MODEL = 'gemini-3.5-flash-lite'
PROMPT_PATH = 'prompts/scalper.txt'
HEADER = '🧪 历史行情分析测试｜不是当前交易信号，不可据此进场'
PLAN_UPLOAD_URL = 'https://goldscalp-telegram.bongsh2002.workers.dev/update-plan'



def candle_range_quality(frame, threshold):
    """Summarize near-flat candle runs without guessing their cause."""
    sample_ranges = (frame.High - frame.Low).astype(float)
    narrow = sample_ranges <= threshold
    longest_run = run = 0
    for is_narrow in narrow.tolist():
        run = run + 1 if is_narrow else 0
        longest_run = max(longest_run, run)
    count = int(narrow.sum())
    ratio = count / len(sample_ranges) if len(sample_ranges) else 0.0
    return {'count': count, 'ratio': round(ratio, 4), 'longest_run': longest_run}


def requires_candle_quality_review(*stats):
    return any(item['ratio'] >= 0.25 and item['longest_run'] >= 6 for item in stats)

def save_record(path, record):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def api_json(response, service, secrets):
    if response.status_code != 200:
        try:
            error = response.json().get('error', {})
            message = error.get('message', '') if isinstance(error, dict) else ''
        except ValueError:
            message = ''
        for secret in secrets:
            if secret:
                message = message.replace(secret, '[REDACTED]')
        raise RuntimeError(f'{service} HTTP {response.status_code}: {message[:600]}')
    return response.json()


def fetch_chart(key, interval, minutes, now, folder):
    response = requests.get(
        'https://api.twelvedata.com/time_series',
        params={'symbol': 'XAU/USD', 'interval': interval, 'outputsize': 160,
                'timezone': 'UTC', 'apikey': key}, timeout=(10, 45))
    data = api_json(response, f'Twelve Data {interval}', [key])
    if data.get('status') != 'ok' or not data.get('values'):
        raise RuntimeError(f'{interval}: data rejected')
    meta = data.get('meta', {})
    if meta.get('symbol') != 'XAU/USD' or meta.get('interval') != interval:
        raise RuntimeError(f'{interval}: unexpected symbol or interval')
    (folder / f'{interval}_response.json').write_text(
        json.dumps({'meta': meta, 'values': data['values']}, ensure_ascii=False), encoding='utf-8')
    frame = pd.DataFrame(data['values'])
    frame.index = pd.to_datetime(frame.pop('datetime'), utc=True, errors='raise')
    if frame.index.has_duplicates or frame.index.isna().any():
        raise RuntimeError(f'{interval}: invalid timestamps')
    frame = frame[['open', 'high', 'low', 'close']].apply(pd.to_numeric, errors='raise')
    frame.columns = ['Open', 'High', 'Low', 'Close']
    frame = frame.sort_index()
    if not frame.map(lambda x: pd.notna(x) and 0 < x < float('inf')).all().all():
        raise RuntimeError(f'{interval}: invalid prices')
    if ((frame.High < frame[['Open', 'Close', 'Low']].max(axis=1)) |
            (frame.Low > frame[['Open', 'Close', 'High']].min(axis=1))).any():
        raise RuntimeError(f'{interval}: invalid OHLC ordering')
    if frame.index.max() > now + pd.Timedelta(seconds=60):
        raise RuntimeError(f'{interval}: future timestamp')
    frame = frame[frame.index + pd.Timedelta(minutes=minutes) <= now]
    if len(frame) < 50:
        raise RuntimeError(f'{interval}: insufficient closed candles')
    frame.to_csv(folder / f'{interval}_closed_ohlc.csv', index_label='timestamp_utc')
    frame.tail(40).to_csv(folder / f'{interval}_ai_ohlc.csv', index_label='timestamp_utc')
    ranges = frame.tail(40).High - frame.tail(40).Low
    # Flag suspicious runs of near-flat candles in both the AI sample and chart window.
    # Thresholds are diagnostic only; they do not infer why the candles are flat.
    narrow_threshold = {'5min': 0.15, '15min': 0.30, '1h': 0.30}.get(interval, 0.30)
    ai_quality = candle_range_quality(frame.tail(40), narrow_threshold)
    chart_quality = candle_range_quality(frame.tail(120), narrow_threshold)
    quality_review_required = requires_candle_quality_review(ai_quality, chart_quality)
    age = (now - (frame.index[-1] + pd.Timedelta(minutes=minutes))).total_seconds() / 60
    diagnostic = {
        'interval': interval, 'candles_available': len(frame), 'candles_sent': 40,
        'last_closed_candle_utc': frame.index[-1].isoformat(),
        'last_closed_candle_myt': frame.index[-1].tz_convert('Asia/Kuala_Lumpur').isoformat(),
        'minutes_since_close': round(age, 2), 'timestamp_stale': bool(age > max(15, minutes * 2)),
        'run_is_myt_weekend': bool(now.tz_convert('Asia/Kuala_Lumpur').dayofweek >= 5),
        'market_session_verified': False,
        'recent_range_min': float(ranges.min()), 'recent_range_max': float(ranges.max()),
        'recent_range_median': float(ranges.median()), 'diagnostic_narrow_range_threshold_usd': narrow_threshold,
        'recent_narrow_range_count': ai_quality['count'],
        'recent_narrow_range_ratio': ai_quality['ratio'],
        'recent_narrow_range_longest_run': ai_quality['longest_run'],
        'chart_window_narrow_range_count': chart_quality['count'],
        'chart_window_narrow_range_ratio': chart_quality['ratio'],
        'chart_window_narrow_range_longest_run': chart_quality['longest_run'],
        'quality_review_required': quality_review_required,
        'quality_verdict': 'REVIEW_REQUIRED' if quality_review_required else 'NO_NARROW_RUN_FLAG',
        'quality_cause': 'UNKNOWN',
        'data_validation_status': 'UNVERIFIED_TEST_ONLY',
        'recent_zero_range_count': int((ranges.abs() <= 0.000000001).sum()),
        'time_gaps_in_sample': int((frame.index.to_series().diff() > pd.Timedelta(minutes=minutes)).sum()),
        'note': '时间新不代表有效行情；窄幅统计为诊断，不判定原因；周末标记不替代交易时段日历。'}
    plot = frame.tail(120).copy()
    plot.index = plot.index.tz_convert('Asia/Kuala_Lumpur').tz_localize(None)
    fig, _ = mpf.plot(plot, type='candle', style='yahoo', volume=False,
                      title=f'XAU/USD {interval} | MYT UTC+8 | HISTORICAL TEST ONLY',
                      figsize=(14, 7), returnfig=True, tight_layout=True)
    buffer = io.BytesIO()
    try:
        fig.savefig(buffer, format='png', dpi=130, bbox_inches='tight')
    finally:
        plt.close(fig)
    image = buffer.getvalue()
    buffer.close()
    (folder / f'{interval}.png').write_bytes(image)
    return frame, image, diagnostic


def extract_json_block(analysis, label):
    match = re.search(r'```' + label + r'\s*(\{.*?\})\s*```', analysis, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(1))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def upload_plan(config, analysis, record):
    meta = {
        'run_id': record['run_id'],
        'created_at_utc': record['created_at_utc'],
        'created_at_myt': record['created_at_myt'],
        'ai_model': MODEL,
        'code_commit': record.get('code_commit', ''),
        'charts': record.get('charts', []),
        'fundamentals': record.get('fundamentals', {}),
        'trade_plan': record.get('trade_plan'),
        'market_watch': record.get('market_watch'),
        'current_price': record.get('current_price'),
        'source': 'github_workflow'
    }
    response = requests.post(
        PLAN_UPLOAD_URL,
        headers={'Authorization': 'Bearer ' + config['PLAN_UPDATE_TOKEN'],
                 'Content-Type': 'application/json'},
        json={'plan': analysis, 'meta': meta}, timeout=(10, 30))
    result = api_json(response, 'Cloudflare plan upload', [config['PLAN_UPDATE_TOKEN']])
    if result.get('ok') is not True:
        raise RuntimeError('Cloudflare plan upload rejected')
    return result


def main():
    now = pd.Timestamp.now(tz='UTC')
    local_now = now.tz_convert('Asia/Kuala_Lumpur')
    if local_now.dayofweek >= 5 or not (8 <= local_now.hour < 23):
        print('Outside configured MYT trading window (weekdays 08:00-23:00); no market APIs called.')
        return 0
    run_id = now.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
    folder = Path('journal') / run_id
    folder.mkdir(parents=True, exist_ok=False)
    record_path = folder / 'record.json'
    record = {'run_id': run_id, 'created_at_utc': now.isoformat(),
              'created_at_myt': now.tz_convert('Asia/Kuala_Lumpur').isoformat(),
              'mode': 'historical_test', 'ai_model': MODEL, 'charts': [],
              'code_commit': os.getenv('GITHUB_SHA', ''),
              'stage': 'configuration', 'status': 'running',
              'telegram': {'attempted': False, 'sent': False},
              'plan_upload': {'attempted': False, 'sent': False},
              'execution': 'manual_only_no_auto_trading'}
    save_record(record_path, record)
    names = ['TWELVEDATA_API_KEY', 'GEMINI_API_KEY', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'PLAN_UPDATE_TOKEN']
    config = {name: os.getenv(name, '').strip() for name in names}
    try:
        missing = [name for name in names if not config[name]]
        if missing:
            raise RuntimeError('Missing Secrets: ' + ', '.join(missing))
        record['stage'] = 'prompt'
        save_record(record_path, record)
        prompt = Path(PROMPT_PATH).read_text(encoding='utf-8').strip()
        if not prompt:
            raise RuntimeError('Empty prompt')
        (folder / 'prompt.txt').write_text(prompt, encoding='utf-8')
        record['prompt_sha256'] = hashlib.sha256(prompt.encode()).hexdigest()
        instruction = (prompt + '\n\n【执行模式】仅历史分析测试，不是实时交易。\n'
                       + HEADER + '\n当前 UTC：' + now.isoformat()
                       + '\n当前大马时间：' + now.tz_convert('Asia/Kuala_Lumpur').isoformat()
                       + '\n不编造宏观背景，不把新时间戳等同于有效行情。只基于以下输入。')
        parts = [{'text': instruction}]
        (folder / 'execution_instruction.txt').write_text(instruction, encoding='utf-8')
        m5_frame = None
        m5_diagnostic = None
        for interval, minutes in [('5min', 5), ('15min', 15), ('1h', 60)]:
            record['stage'] = 'fetch_' + interval
            save_record(record_path, record)
            frame, image, diagnostic = fetch_chart(config['TWELVEDATA_API_KEY'], interval, minutes, now, folder)
            record['charts'].append(diagnostic)
            if interval == '5min':
                m5_frame = frame
                m5_diagnostic = diagnostic
            text = (interval + ' 已收线 OHLC，UTC：\n'
                    + frame.tail(40).to_csv(index_label='timestamp_utc')
                    + '\n程序诊断：' + json.dumps(diagnostic, ensure_ascii=False))
            (folder / f'{interval}_ai_text.txt').write_text(text, encoding='utf-8')
            parts.extend([{'text': text}, {'inline_data': {'mime_type': 'image/png',
                          'data': base64.b64encode(image).decode('ascii')}}])
            save_record(record_path, record)
        record['stage'] = 'fundamentals'
        save_record(record_path, record)
        fundamentals = collect_fundamentals(config['TWELVEDATA_API_KEY'], now, folder)
        record['fundamentals'] = {
            'calendar_event_count': len(fundamentals['calendar_events']),
            'calendar_events': fundamentals['calendar_events'],
            'calendar_coverage': fundamentals['calendar_coverage'],
            'currency_strength': fundamentals['currency_strength'],
            'errors': fundamentals['errors']
        }
        parts.append({'text': fundamentals['context']})
        save_record(record_path, record)
        record['stage'] = 'gemini'
        save_record(record_path, record)
        response = requests.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent',
            headers={'x-goog-api-key': config['GEMINI_API_KEY']},
            json={'contents': [{'role': 'user', 'parts': parts}],
                  'generationConfig': {'temperature': 0.2, 'maxOutputTokens': 2048}}, timeout=(10, 120))
        result = api_json(response, 'Gemini', list(config.values()))
        candidates = result.get('candidates', [])
        if not candidates:
            raise RuntimeError('Gemini: no candidates')
        candidate = candidates[0]
        record['gemini_finish_reason'] = candidate.get('finishReason')
        analysis = '\n'.join(p.get('text', '') for p in candidate.get('content', {}).get('parts', [])
                             if not p.get('thought')).strip()
        record['ai_raw_output'] = analysis
        record['gemini_usage'] = result.get('usageMetadata', {})
        save_record(record_path, record)
        if not analysis or candidate.get('finishReason') != 'STOP':
            raise RuntimeError('Gemini output missing or incomplete; Telegram skipped')
        trade_plan = extract_json_block(analysis, 'trade_plan')
        market_watch = extract_json_block(analysis, 'market_watch')
        safety_reasons = []
        if m5_diagnostic is None:
            safety_reasons.append('M5 diagnostic unavailable')
        else:
            if m5_diagnostic.get('timestamp_stale'):
                safety_reasons.append('M5 data stale')
            if m5_diagnostic.get('run_is_myt_weekend'):
                safety_reasons.append('weekend')
            for chart_diagnostic in record.get('charts', []):
                if chart_diagnostic.get('quality_review_required'):
                    safety_reasons.append(
                        chart_diagnostic.get('interval', 'unknown')
                        + ' suspicious near-flat candle run; data quality review required'
                    )
            if not m5_diagnostic.get('market_session_verified'):
                safety_reasons.append('market session unverified')
        safety_gate = {'passed': not safety_reasons, 'reasons': safety_reasons}
        record['safety_gate'] = safety_gate
        if not safety_gate['passed']:
            analysis = re.sub(r'状态：\s*(WAIT|APPROACH|CONFIRMED)([^\n]*)', '状态：WAIT（安全闸拦截）', analysis, count=1)
            if trade_plan and trade_plan.get('status') == 'ENTRY_READY':
                trade_plan['status'] = 'WAIT'
                trade_plan['blocked_reason'] = '; '.join(safety_reasons)
            if market_watch:
                for zone in market_watch.get('zones', []) or []:
                    if zone.get('status') == 'APPROACH':
                        zone['status'] = 'WAIT'
        record['trade_plan'] = trade_plan
        record['market_watch'] = market_watch
        current_price = float(m5_frame.Close.iloc[-1]) if m5_frame is not None else None
        if current_price is not None:
            record['current_price'] = current_price
        (folder / 'trade_plan.json').write_text(
            json.dumps(trade_plan, ensure_ascii=False, indent=2), encoding='utf-8')
        (folder / 'market_watch.json').write_text(
            json.dumps(market_watch, ensure_ascii=False, indent=2), encoding='utf-8')
        save_record(record_path, record)
        if not safety_gate['passed']:
            message = (HEADER + '\n\n状态：WAIT（安全闸拦截）\n'
                       + '时间：' + record['created_at_myt'] + '\n'
                       + ('价格：' + f'{current_price:.2f}' + '\n' if current_price is not None else '')
                       + '原因：' + '; '.join(safety_reasons) + '\n'
                       + '未满足实时信号安全条件；不提供 ENTRY_READY。')
        else:
            message = HEADER + '\n\n' + analysis.removeprefix(HEADER).lstrip()
            if trade_plan:
                message += '\n\n📋 ICT/SMC Trade Plan（结构参考，非自动下单指令）\n'
                message += '```json\n' + json.dumps(trade_plan, ensure_ascii=False, indent=2) + '\n```'
                message += '\n实际 entry 与 SL 由交易者根据 broker 成交情况决定；lot 与实际风险在此之后才计算。'
        if len(message.encode('utf-16-le')) // 2 > 4000:
            raise RuntimeError('Analysis too long; saved in journal; Telegram skipped rather than truncating')
        record['stage'] = 'telegram'
        record['telegram'] = {'attempted': True, 'sent': False}
        save_record(record_path, record)
        response = requests.post(
            f"https://api.telegram.org/bot{config['TELEGRAM_BOT_TOKEN']}/sendMessage",
            data={'chat_id': config['TELEGRAM_CHAT_ID'], 'text': message}, timeout=(10, 60))
        sent = api_json(response, 'Telegram', list(config.values()))
        if sent.get('ok') is not True:
            raise RuntimeError('Telegram rejected message')
        record['telegram'] = {'attempted': True, 'sent': True, 'truncated': False,
                              'message_id': sent.get('result', {}).get('message_id')}
        record['stage'] = 'plan_upload'
        record['plan_upload'] = {'attempted': True, 'sent': False}
        save_record(record_path, record)
        try:
            upload_result = upload_plan(config, analysis, record)
            record['plan_upload'] = {'attempted': True, 'sent': True,
                                     'saved_at': upload_result.get('saved_at')}
        except Exception as upload_error:
            upload_message = str(upload_error) if isinstance(upload_error, RuntimeError) else type(upload_error).__name__
            for secret in config.values():
                if secret:
                    upload_message = upload_message.replace(secret, '[REDACTED]')
            record['plan_upload'] = {'attempted': True, 'sent': False, 'error': upload_message[:500]}
            raise RuntimeError('Cloudflare plan upload failed: ' + upload_message)
        record['status'] = 'completed'
        record['stage'] = 'completed'
        save_record(record_path, record)
        print(f'历史测试完成；Journal: {folder}')
        return 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        for secret in config.values():
            if secret:
                message = message.replace(secret, '[REDACTED]')
        record['status'] = 'failed'
        record['error'] = message[:1000]
        save_record(record_path, record)
        print(f"测试停止于 {record['stage']}: {record['error']}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
