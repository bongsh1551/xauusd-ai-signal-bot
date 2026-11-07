import json

from zone_lifecycle import apply_zone_lifecycle


def _kwargs(closes):
    rows = []
    for close in closes:
        rows.append(','.join(['2026-11-07 00:00:00', str(close - 1), str(close + 1), str(close - 1), str(close)]))
    csv = 'timestamp,open,high,low,close\n' + '\n'.join(rows)
    return {'json': {'contents': [{'parts': [{'text': '5min 已收线 OHLC，UTC：\n' + csv}]}]}}


def _analysis(status='WAIT'):
    zone = {'direction': 'SELL', 'zone_type': 'supply', 'low': 100.0, 'high': 101.0,
            'status': status, 'timeframe': 'M15', 'origin_candle_time': '2026-11-07T00:00:00Z',
            'entry_trigger': 'bearish confirmation', 'cancel_condition': 'M5 close above high'}
    watch = {'zones': [zone]}
    return '状态：' + status + '\n```market_watch\n' + json.dumps(watch) + '\n```'


def test_normal_zone_remains_wait():
    text, diagnostic = apply_zone_lifecycle(_analysis(), _kwargs([100.0, 100.5]))
    assert 'WAIT' in text
    assert diagnostic['changes'] == []


def test_one_close_through_marks_broken():
    text, diagnostic = apply_zone_lifecycle(_analysis(), _kwargs([100.0, 101.5]))
    assert 'BROKEN' in text
    assert diagnostic['changes'][0]['action'] == 'BROKEN'


def test_two_close_throughs_invalidate():
    text, diagnostic = apply_zone_lifecycle(_analysis(), _kwargs([101.5, 101.6]))
    assert 'INVALIDATED' in text
    assert diagnostic['changes'][0]['action'] == 'INVALIDATED'


def test_missing_origin_forces_wait():
    zone = {'direction': 'SELL', 'zone_type': 'supply', 'low': 100.0, 'high': 101.0,
            'status': 'APPROACH', 'entry_trigger': 'x', 'cancel_condition': 'y'}
    watch = {'zones': [zone]}
    text = '状态：WAIT\n```market_watch\n' + json.dumps(watch) + '\n```'
    updated, diagnostic = apply_zone_lifecycle(text, _kwargs([100.0, 100.5]))
    assert 'MISSING_STABLE_SCENARIO_ID' in updated
    assert diagnostic['changes'][0]['action'] == 'WAIT'
