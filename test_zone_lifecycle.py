import json
import pytest

from zone_lifecycle import apply_zone_lifecycle


@pytest.fixture(autouse=True)
def isolated_lifecycle_state(tmp_path, monkeypatch):
    monkeypatch.setenv('ZONE_LIFECYCLE_STATE_PATH', str(tmp_path / 'zone_lifecycle_state.json'))


def _kwargs(closes):
    rows = []
    for close in closes:
        rows.append(','.join(['2026-11-07 00:00:00', str(close - 1), str(close + 1), str(close - 1), str(close)]))
    csv = 'timestamp,open,high,low,close\n' + '\n'.join(rows)
    return {'json': {'contents': [{'parts': [{'text': '5min 已收线 OHLC，UTC：\n' + csv}]}]}}


def _analysis(status='WAIT', h1_bias='bearish', currency='neutral', calendar='low', confirmations=True, direction='SELL', confirmation_verified=True):
    zone = {'direction': direction, 'zone_type': 'supply' if direction == 'SELL' else 'demand',
            'low': 100.0, 'high': 101.0, 'status': status, 'timeframe': 'M15',
            'origin_candle_time': '2026-11-07T00:00:00Z',
            'entry_trigger': 'bearish confirmation' if direction == 'SELL' else 'bullish confirmation',
            'cancel_condition': 'M5 close above high' if direction == 'SELL' else 'M5 close below low',
            'h1_bias': h1_bias,
            'bearish_confirmation_verified': confirmation_verified if direction == 'SELL' else None,
            'bullish_confirmation_verified': confirmation_verified if direction == 'BUY' else None,
            'confirmations': {'sweep': confirmations, 'rejection': confirmations,
                              'displacement': confirmations, 'mss': confirmations}}
    watch = {'zones': [zone], 'news_bias': 'bearish' if direction == 'SELL' else 'bullish',
             'currency_strength': currency, 'calendar_risk': calendar,
             'fundamental_note': 'context available'}
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


def test_buy_normal_confluence_approach():
    text, diagnostic = apply_zone_lifecycle(
        _analysis(h1_bias='bullish', direction='BUY'), _kwargs([100.5, 100.0]))
    assert 'APPROACH' in text
    assert diagnostic['changes'][0]['action'] == 'APPROACH'


def test_buy_missing_confirmation_forces_wait():
    text, diagnostic = apply_zone_lifecycle(
        _analysis(h1_bias='bullish', direction='BUY', confirmations=False), _kwargs([100.5, 100.0]))
    assert 'TECHNICAL_CONFIRMATION_MISSING' in text
    assert diagnostic['changes'][0]['action'] == 'WAIT'


def test_buy_h1_bias_conflict_forces_wait():
    text, diagnostic = apply_zone_lifecycle(
        _analysis(h1_bias='bearish', direction='BUY'), _kwargs([100.5, 100.0]))
    assert 'H1_BIAS_CONFLICT' in text
    assert diagnostic['changes'][0]['action'] == 'WAIT'


def test_buy_usd_conflict_forces_wait():
    text, diagnostic = apply_zone_lifecycle(
        _analysis(h1_bias='bullish', direction='BUY', currency='usd_bearish'), _kwargs([100.5, 100.0]))
    assert 'USD_STRENGTH_CONFLICT' in text
    assert diagnostic['changes'][0]['action'] == 'WAIT'


def test_buy_high_impact_news_pauses():
    text, diagnostic = apply_zone_lifecycle(
        _analysis(h1_bias='bullish', direction='BUY', calendar='high_impact'), _kwargs([100.5, 100.0]))
    assert 'HIGH_IMPACT_NEWS_WINDOW' in text
    assert diagnostic['changes'][0]['action'] == 'PAUSED'


def test_buy_confirmation_not_verified_forces_wait():
    text, diagnostic = apply_zone_lifecycle(
        _analysis(h1_bias='bullish', direction='BUY', confirmation_verified=False), _kwargs([100.5, 100.0]))
    assert 'CONFIRMATION_NOT_VERIFIED' in text
    assert diagnostic['changes'][0]['action'] == 'WAIT'
