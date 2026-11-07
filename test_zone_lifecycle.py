import json

from zone_lifecycle import apply_zone_lifecycle


def _kwargs(closes):
    rows = []
    for close in closes:
        rows.append(','.join(['2026-11-07 00:00:00', str(close - 1), str(close + 1), str(close - 1), str(close)]))
    csv = 'timestamp,open,high,low,close\n' + '\n'.join(rows)
    return {'json': {'contents': [{'parts': [{'text': '5min 已收线 OHLC，UTC：\n' + csv}]}]}}


def _analysis(status='WAIT', h1_bias='bearish', currency='neutral', calendar='low', confirmations=True):
    zone = {'direction': 'SELL', 'zone_type': 'supply', 'low': 100.0, 'high': 101.0,
            'status': status, 'timeframe': 'M15', 'origin_candle_time': '2026-11-07T00:00:00Z',
            'entry_trigger': 'bearish confirmation', 'cancel_condition': 'M5 close above high',
            'h1_bias': h1_bias,
            'confirmations': {'sweep': confirmations, 'rejection': confirmations,
                              'displacement': confirmations, 'mss': confirmations}}
    watch = {'zones': [zone], 'news_bias': 'bearish', 'currency_strength': currency,
             'calendar_risk': calendar, 'fundamental_note': 'context available'}
    return '状态：' + status + '\n```market_watch\n' + json.dumps(watch) + '\n```'


def test_normal_confluence_approach():
    text, diagnostic = apply_zone_lifecycle(_analysis(), _kwargs([100.0, 100.5]))
    assert 'APPROACH' in text
    assert diagnostic['changes'][0]['action'] == 'APPROACH'


def test_missing_fundamental_forces_wait():
    import re as _re
    text = _analysis()
    text = _re.sub(r'"news_bias": "bearish",|"currency_strength": "neutral",|"calendar_risk": "low",|"fundamental_note": "context available",', '', text)
    updated, diagnostic = apply_zone_lifecycle(text, _kwargs([100.0, 100.5]))
    assert 'FUNDAMENTAL_CONTEXT_MISSING' in updated
    assert diagnostic['changes'][0]['action'] == 'WAIT'


def test_usd_conflict_forces_wait():
    text, diagnostic = apply_zone_lifecycle(_analysis(currency='usd_bullish'), _kwargs([100.0, 100.5]))
    assert 'USD_STRENGTH_CONFLICT' in text
    assert diagnostic['changes'][0]['action'] == 'WAIT'


def test_high_impact_news_pauses():
    text, diagnostic = apply_zone_lifecycle(_analysis(calendar='high_impact'), _kwargs([100.0, 100.5]))
    assert 'HIGH_IMPACT_NEWS_WINDOW' in text
    assert diagnostic['changes'][0]['action'] == 'PAUSED'


def test_missing_confirmation_forces_wait():
    text, diagnostic = apply_zone_lifecycle(_analysis(confirmations=False), _kwargs([100.0, 100.5]))
    assert 'TECHNICAL_CONFIRMATION_MISSING' in text
    assert diagnostic['changes'][0]['action'] == 'WAIT'
