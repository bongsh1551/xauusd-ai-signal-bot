import json
import os
import tempfile
from pathlib import Path

import pytest

from test_zone_lifecycle import _analysis, _kwargs
from zone_lifecycle import apply_zone_lifecycle
from sensenova_runner import validate_analysis
from main import extract_json_block
from lifecycle_contract import normalize_lifecycle_contract


def _state_path(tmp_path):
    path = tmp_path / 'zone_lifecycle_state.json'
    os.environ['ZONE_LIFECYCLE_STATE_PATH'] = str(path)
    return path


def test_true_range_uses_high_low_previous_close(tmp_path):
    _state_path(tmp_path)
    rows = []
    for close, high, low in [(100.0, 101.0, 99.0), (101.0, 103.0, 100.0)]:
        rows.append(','.join(['2026-11-07 00:00:00', str(close - 1), str(high), str(low), str(close)]))
    csv = 'timestamp,open,high,low,close\n' + '\n'.join(rows)
    kwargs = {'json': {'contents': [{'parts': [{'text': '5min 已收线 OHLC，UTC：\n' + csv}]}]}}
    _, diagnostic = apply_zone_lifecycle(_analysis(), kwargs)
    assert diagnostic['atr'] == pytest.approx(3.0)


@pytest.mark.parametrize('closes,calendar,expected', [
    ([100.5, 102.0], 'low', 'BROKEN'),
    ([102.0, 103.0], 'low', 'INVALIDATED'),
    ([100.0, 100.5], 'high_impact', 'PAUSED'),
])
def test_real_lifecycle_output_validates_without_alert(tmp_path, closes, calendar, expected):
    _state_path(tmp_path)
    updated, diagnostic = apply_zone_lifecycle(_analysis(status='APPROACH', calendar=calendar), _kwargs(closes))
    assert validate_analysis(updated) == 'WAIT'
    zone = extract_json_block(updated, 'market_watch')['zones'][0]
    assert zone['status'] == 'WAIT'
    assert zone['lifecycle_state'] == expected
    assert zone['alert_allowed'] is False
    assert diagnostic['contract_blocks'][0]['lifecycle_state'] == expected


def test_invalidated_scenario_does_not_revive_next_run(tmp_path):
    state_path = _state_path(tmp_path)
    updated, _ = apply_zone_lifecycle(_analysis(), _kwargs([102.0, 103.0]))
    assert extract_json_block(updated, 'market_watch')['zones'][0]['lifecycle_state'] == 'INVALIDATED'
    updated_again, diagnostic = apply_zone_lifecycle(_analysis(), _kwargs([100.0, 100.5]))
    zone = extract_json_block(updated_again, 'market_watch')['zones'][0]
    assert zone['status'] == 'INVALIDATED'
    assert zone['lifecycle_reason'] == 'PRIOR_INVALIDATION_PERSISTED'
    assert zone['alert_allowed'] is False
    assert diagnostic['persisted_invalidations'] == ['SELL:M15:2026-11-07T00:00:00Z']
    assert state_path.exists()


def test_blocked_confirmed_plan_removed(tmp_path):
    _state_path(tmp_path)
    original = _analysis(status='CONFIRMED') + '\n```trade_plan\n{"status":"ENTRY_READY"}\n```'
    updated, _ = apply_zone_lifecycle(original, _kwargs([102.0, 103.0]))
    assert validate_analysis(updated) == 'WAIT'
    assert extract_json_block(updated, 'trade_plan') is None


def test_header_follows_zone_states(tmp_path):
    _state_path(tmp_path)
    updated, _ = apply_zone_lifecycle(_analysis(status='CONFIRMED'), _kwargs([100.0, 100.5]))
    assert validate_analysis(updated) == 'APPROACH'
    updated_wait, _ = apply_zone_lifecycle(_analysis(status='CONFIRMED', confirmations=False), _kwargs([100.0, 100.5]))
    assert validate_analysis(updated_wait) == 'WAIT'


def test_unknown_state_not_silently_accepted(tmp_path):
    _state_path(tmp_path)
    with pytest.raises(RuntimeError):
        validate_analysis(_analysis(status='WAIT').replace('"status": "WAIT"', '"status": "UNKNOWN"'))


def test_contract_adapter_preserves_terminal_evidence():
    watch = {'zones': [{'status': 'INVALIDATED', 'direction': 'SELL'}]}
    text, blocked = normalize_lifecycle_contract('状态：APPROACH', watch)
    assert text == '状态：WAIT'
    assert blocked and watch['zones'][0]['lifecycle_state'] == 'INVALIDATED'
