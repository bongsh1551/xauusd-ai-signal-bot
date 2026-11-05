import json
from pathlib import Path

import pandas as pd
import requests

CALENDAR_URL = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'
FX_CACHE_PATH = Path('.cache/fx_strength.json')
FX_CACHE_UPDATED = Path('.cache/fx_strength.updated')
FX_CACHE_MAX_AGE_MINUTES = 70


def _json(response, service):
    if response.status_code != 200:
        raise RuntimeError(f'{service} HTTP {response.status_code}')
    return response.json()


def fetch_calendar(now, folder):
    try:
        response = requests.get(CALENDAR_URL, timeout=(10, 30))
        data = _json(response, 'Forex Factory calendar')
        if not isinstance(data, list):
            raise RuntimeError('calendar payload is not a list')
        (folder / 'calendar_raw.json').write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        selected = []
        timestamps = []
        for item in data:
            try:
                event_time = pd.Timestamp(item.get('date'), tz='UTC')
            except Exception:
                continue
            timestamps.append(event_time)
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
        horizon_end = now + pd.Timedelta(hours=24)
        latest_event = max(timestamps) if timestamps else None
        coverage = 'full' if latest_event is not None and latest_event >= horizon_end else 'partial'
        status = 'ok' if selected else 'no_events'
        return {'status': status, 'events': selected, 'error': None,
                'coverage': coverage,
                'calendar_last_event_utc': latest_event.isoformat() if latest_event is not None else None,
                'requested_horizon_end_utc': horizon_end.isoformat()}
    except Exception as exc:
        return {'status': 'error', 'events': [], 'error': str(exc)[:300],
                'coverage': 'unavailable', 'calendar_last_event_utc': None,
                'requested_horizon_end_utc': (now + pd.Timedelta(hours=24)).isoformat()}


def fetch_fx(key, symbol, now, folder):
    response = requests.get(
        'https://api.twelvedata.com/time_series',
        params={'symbol': symbol, 'interval': '1h', 'outputsize': 10,
                'timezone': 'UTC', 'apikey': key}, timeout=(10, 30))
    data = _json(response, f'Twelve Data {symbol}')
    if data.get('status') != 'ok' or not data.get('values'):
        raise RuntimeError(f'{symbol}: data rejected')
    frame = pd.DataFrame(data['values'])
    frame.index = pd.to_datetime(frame.pop('datetime'), utc=True, errors='raise')
    frame = frame[['open', 'high', 'low', 'close']].apply(pd.to_numeric, errors='raise')
    frame.columns = ['Open', 'High', 'Low', 'Close']
    frame = frame.sort_index()
    frame = frame[frame.index + pd.Timedelta(hours=1) <= now]
    if len(frame) < 5:
        raise RuntimeError(f'{symbol}: insufficient closed H1 candles')
    last_close = float(frame.Close.iloc[-1])
    previous_close = float(frame.Close.iloc[-5])
    change_pct = (last_close / previous_close - 1) * 100
    age_minutes = (now - (frame.index[-1] + pd.Timedelta(hours=1))).total_seconds() / 60
    result = {
        'symbol': symbol,
        'last_close': last_close,
        'change_4h_pct': round(change_pct, 4),
        'last_closed_utc': frame.index[-1].isoformat(),
        'closed_h1_candles': int(len(frame)),
        'minutes_since_close': round(age_minutes, 2),
        'stale': bool(age_minutes > 120)
    }
    (folder / f"{symbol.replace('/', '').lower()}_h1.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def load_fx_cache(now):
    try:
        cache = json.loads(FX_CACHE_PATH.read_text(encoding='utf-8'))
        # Current format stores each pair independently so one failed symbol
        # does not force the other pair to be fetched again.
        if isinstance(cache.get('symbols'), dict):
            symbols = {}
            for symbol, item in cache['symbols'].items():
                if not isinstance(item, dict) or not isinstance(item.get('data'), dict):
                    continue
                cached_at = pd.Timestamp(item['cached_at_utc'])
                age = (now - cached_at).total_seconds() / 60
                if 0 <= age <= FX_CACHE_MAX_AGE_MINUTES:
                    symbols[symbol] = {'cached_at_utc': item['cached_at_utc'], 'data': item['data']}
            retry_after = cache.get('retry_after_utc')
            retry_pending = False
            if retry_after:
                retry_pending = pd.Timestamp(retry_after) > now
            return {'symbols': symbols, 'retry_pending': retry_pending}
        # Read the previous all-or-nothing cache format during rollout.
        cached_at = pd.Timestamp(cache['cached_at_utc'])
        age = (now - cached_at).total_seconds() / 60
        data = cache['symbols']
        if 0 <= age <= FX_CACHE_MAX_AGE_MINUTES and all(
                isinstance(data.get(symbol), dict) for symbol in ('EUR/USD', 'USD/JPY')):
            return {'symbols': {symbol: {'cached_at_utc': cached_at.isoformat(), 'data': value}
                            for symbol, value in data.items()}, 'retry_pending': False}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {'symbols': {}, 'retry_pending': False}


def save_fx_cache(symbols, now, retry_after=None):
    FX_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'updated_at_utc': now.isoformat(),
        'symbols': symbols,
        'retry_after_utc': retry_after.isoformat() if retry_after is not None else None
    }
    temporary = FX_CACHE_PATH.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(FX_CACHE_PATH)
    FX_CACHE_UPDATED.write_text(now.isoformat(), encoding='utf-8')


def collect_fundamentals(key, now, folder):
    calendar = fetch_calendar(now, folder)
    errors = {}
    FX_CACHE_UPDATED.unlink(missing_ok=True)
    cache = load_fx_cache(now)
    cached_symbols = cache['symbols']
    values = {}
    cache_symbols = {}
    attempted_refresh = False
    retry_after = None

    for symbol in ('EUR/USD', 'USD/JPY'):
        if symbol in cached_symbols:
            values[symbol] = cached_symbols[symbol]
            cache_symbols[symbol] = {
                'cached_at_utc': now.isoformat(),
                'data': cached_symbols[symbol]
            }
            continue

        if cache['retry_pending']:
            values[symbol] = None
            errors[symbol.replace('/', '')] = 'refresh temporarily deferred after recent API failure'
            # Preserve the original cached timestamp/data if it exists but is stale.
            continue

        attempted_refresh = True
        try:
            value = fetch_fx(key, symbol, now, folder)
            values[symbol] = value
            cache_symbols[symbol] = {'cached_at_utc': now.isoformat(), 'data': value}
        except Exception as exc:
            values[symbol] = None
            errors[symbol.replace('/', '')] = str(exc)[:300]
            retry_after = now + pd.Timedelta(minutes=15)

    # Persist successful pairs and a short failure cooldown. This avoids
    # repeatedly spending credits on a failing endpoint every 5-minute run.
    if attempted_refresh:
        save_fx_cache(cache_symbols, now, retry_after)

    eurusd, usdjpy = values.get('EUR/USD'), values.get('USD/JPY')
    for symbol, value in (('EUR/USD', eurusd), ('USD/JPY', usdjpy)):
        if value is not None:
            (folder / f"{symbol.replace('/', '').lower()}_h1.json").write_text(
                json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    strength = currency_strength(eurusd, usdjpy)
    strength['data_source'] = 'cache' if not attempted_refresh else 'live_api'
    context = build_context(now, calendar, strength, errors)
    (folder / 'market_context.txt').write_text(context, encoding='utf-8')
    return {
        'calendar_events': calendar['events'],
        'calendar_coverage': calendar.get('coverage', 'unavailable'),
        'currency_strength': strength,
        'errors': errors,
        'context': context
    }

def currency_strength(eurusd, usdjpy):
    if not eurusd or not usdjpy:
        return {'status': 'UNAVAILABLE', 'usd_vs_eur_pct': None,
                'usd_vs_jpy_pct': None, 'reason': 'EURUSD or USDJPY data unavailable'}
    if eurusd.get('stale') or usdjpy.get('stale'):
        return {'status': 'UNAVAILABLE', 'usd_vs_eur_pct': None,
                'usd_vs_jpy_pct': None,
                'reason': 'EURUSD or USDJPY last closed H1 candle is older than 120 minutes',
                'eurusd': eurusd, 'usdjpy': usdjpy}
    usd_vs_eur = -float(eurusd['change_4h_pct'])
    usd_vs_jpy = float(usdjpy['change_4h_pct'])
    if usd_vs_eur > 0 and usd_vs_jpy > 0:
        status = 'USD_STRONG'
    elif usd_vs_eur < 0 and usd_vs_jpy < 0:
        status = 'USD_WEAK'
    else:
        status = 'MIXED'
    return {'status': status, 'usd_vs_eur_pct': round(usd_vs_eur, 4),
            'usd_vs_jpy_pct': round(usd_vs_jpy, 4),
            'method': 'last 4 closed H1 candles; consistent direction and freshness required',
            'eurusd': eurusd, 'usdjpy': usdjpy}


def build_context(now, calendar, strength, errors):
    lines = [
        '【Market Context｜程序提供，不得编造】',
        '当前 UTC：' + now.isoformat(),
        '当前大马时间：' + now.tz_convert('Asia/Kuala_Lumpur').isoformat(),
        ''
    ]
    lines.append('【Fundamental：经济日历】')
    lines.append('覆盖状态：' + calendar.get('coverage', 'unavailable') +
                 '；请求范围截至：' + str(calendar.get('requested_horizon_end_utc')))
    if calendar['status'] == 'ok':
        lines.append('状态：已获取；未来 24 小时高/中影响力事件 ' + str(len(calendar['events'])) + ' 个。')
        for event in calendar['events']:
            lines.append('- ' + json.dumps(event, ensure_ascii=False))
    elif calendar['status'] == 'no_events':
        lines.append('状态：已获取，但未来 24 小时没有高/中影响力事件。')
    else:
        lines.append('状态：获取失败。错误：' + str(calendar['error']))
    lines.append('')
    lines.append('【Currency Strength：EURUSD + USDJPY】')
    lines.append(json.dumps(strength, ensure_ascii=False))
    lines.extend([
        '',
        '解读规则：',
        '1. USD_STRONG：美元对欧元与日元最近 4 根 H1 已收线均走强且数据不陈旧；通常对黄金构成压力，但不是自动 SELL。',
        '2. USD_WEAK：美元对欧元与日元最近 4 根 H1 已收线均走弱且数据不陈旧；通常对黄金构成支持，但不是自动 BUY。',
        '3. MIXED：两个货币对方向不一致，不能声称美元全面走强或走弱。',
        '4. UNAVAILABLE：资料不足或数据陈旧，不要编造美元方向。',
        '5. 这是 intermarket confluence，不是 Fundamental 新闻，也不是黄金进场信号；最终必须与 XAUUSD H1/M15/M5 结构共振。',
        '6. 没有真实 order flow、volume 或订单簿资料时，不得声称看到订单流。',
        ''
    ])
    lines.append('【Fundamental 使用规则】')
    lines.extend([
        '1. 经济日历用于识别可能影响 USD、利率预期、风险情绪或黄金流动性的事件。',
        '2. 新闻与数据是 confluence，不是自动禁止交易的过滤器。',
        '3. 高影响力事件临近时，提醒波动、spread 与流动性风险；事件就在几分钟内时优先 WAIT 或要求更强确认。',
        '4. 不预测数据结果；只说明可能情景与结构失效条件。',
        '5. 先分别说明 Fundamental status、calendar coverage 与 Currency Strength status；证据不足时明确写“不明确”，不强行给方向。',
        ''
    ])
    if errors:
        lines.append('数据错误：' + json.dumps(errors, ensure_ascii=False))
        lines.append('')
    lines.append('请在分析开头分别给出：Fundamental status、calendar coverage、USD strength status，以及它们是否与 XAUUSD 结构共振；再进行 ICT/SMC 分析。')
    return '\n'.join(lines)
