import json

import pandas as pd
import requests

CALENDAR_URL = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'


def _json(response, service):
    if response.status_code != 200:
        raise RuntimeError(f'{service} HTTP {response.status_code}')
    return response.json()


def fetch_calendar(now, folder):
    response = requests.get(CALENDAR_URL, timeout=(10, 30))
    data = _json(response, 'Forex Factory calendar')
    (folder / 'calendar_raw.json').write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    selected = []
    for item in data:
        try:
            event_time = pd.Timestamp(item.get('date'), tz='UTC')
        except Exception:
            continue
        if not (now <= event_time <= now + pd.Timedelta(hours=24)):
            continue
        impact = str(item.get('impact', '')).strip().lower()
        if impact not in ('high', 'medium'):
            continue
        selected.append({
            'time_utc': event_time.isoformat(),
            'time_myt': event_time.tz_convert('Asia/Kuala_Lumpur').isoformat(),
            'currency': item.get('country', ''),
            'impact': impact,
            'title': item.get('title', ''),
            'forecast': item.get('forecast', ''),
            'previous': item.get('previous', '')
        })
    selected.sort(key=lambda x: x['time_utc'])
    (folder / 'calendar_selected.json').write_text(
        json.dumps(selected, ensure_ascii=False, indent=2), encoding='utf-8')
    return selected


def fetch_dxy(key, now, folder):
    response = requests.get(
        'https://api.twelvedata.com/quote',
        params={'symbol': 'DXY', 'apikey': key}, timeout=(10, 30))
    data = _json(response, 'Twelve Data DXY quote')
    if data.get('status') == 'error':
        raise RuntimeError('Twelve Data DXY quote rejected: ' + str(data.get('message', ''))[:200])
    quote = {
        'symbol': data.get('symbol', 'DXY'),
        'price': data.get('close'),
        'change': data.get('change'),
        'percent_change': data.get('percent_change'),
        'high': data.get('high'),
        'low': data.get('low'),
        'open': data.get('open'),
        'previous_close': data.get('previous_close'),
        'fetched_at_utc': now.isoformat()
    }
    (folder / 'dxy_quote.json').write_text(
        json.dumps(quote, ensure_ascii=False, indent=2), encoding='utf-8')
    return quote


def build_context(now, events, dxy, errors):
    lines = [
        '【Fundamental Context｜程序提供，不得编造】',
        '当前 UTC：' + now.isoformat(),
        '当前大马时间：' + now.tz_convert('Asia/Kuala_Lumpur').isoformat(),
        ''
    ]
    if dxy:
        lines.extend([
            'DXY 美元指数：',
            json.dumps(dxy, ensure_ascii=False),
            '解读要求：DXY 上升通常对黄金构成压力，下降通常支持黄金；但这只是 confluence，不是机械反向规则。'
        ])
    else:
        lines.append('DXY 美元指数：未提供或获取失败。')
    lines.append('')
    if events:
        lines.append('未来 24 小时高/中影响力经济事件：')
        for event in events:
            lines.append('- ' + json.dumps(event, ensure_ascii=False))
        lines.extend([
            '',
            '新闻使用规则：',
            '1. 先判断事件是否可能改变 USD strength、利率预期、风险情绪或黄金流动性。',
            '2. 将其作为 Bias confluence，与 H1/M15/M5 结构一起判断；不要因为即将有新闻就自动禁止交易。',
            '3. 高影响力事件前后，明确提醒波动与 spread 风险；若事件就在几分钟内，优先 WAIT 或要求更严格确认。',
            '4. 不预测数据结果；只说明可能情景与结构失效条件。'
        ])
    else:
        lines.append('未来 24 小时高/中影响力经济事件：未提供或获取失败。')
    if errors:
        lines.append('')
        lines.append('Fundamental 数据错误：' + json.dumps(errors, ensure_ascii=False))
    lines.append('')
    lines.append('请在分析开头先建立今日 Fundamental Bias：USD bullish / bearish / neutral，以及对 XAUUSD 的倾向；再结合 ICT/SMC 结构。')
    return '\n'.join(lines)


def collect_fundamentals(key, now, folder):
    errors = {}
    events = []
    dxy = None
    try:
        events = fetch_calendar(now, folder)
    except Exception as exc:
        errors['calendar'] = str(exc)[:300]
    try:
        dxy = fetch_dxy(key, now, folder)
    except Exception as exc:
        errors['dxy'] = str(exc)[:300]
    context = build_context(now, events, dxy, errors)
    (folder / 'fundamentals_context.txt').write_text(context, encoding='utf-8')
    return {'calendar_events': events, 'dxy': dxy, 'errors': errors, 'context': context}
