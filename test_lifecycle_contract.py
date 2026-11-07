import json
import pytest
from test_zone_lifecycle import _analysis, _kwargs
from zone_lifecycle import apply_zone_lifecycle
from sensenova_runner import validate_analysis
from main import extract_json_block
from lifecycle_contract import normalize_lifecycle_contract

@pytest.mark.parametrize('closes,calendar,expected', [
    ([100.5, 102.0], 'low', 'BROKEN'),
    ([102.0, 103.0], 'low', 'INVALIDATED'),
    ([100.0, 100.5], 'high_impact', 'PAUSED'),
])
def test_real_lifecycle_output_validates_without_alert(closes, calendar, expected):
    updated, diagnostic = apply_zone_lifecycle(_analysis(status='APPROACH', calendar=calendar), _kwargs(closes))
    assert validate_analysis(updated) == 'WAIT'
    zone = extract_json_block(updated, 'market_watch')['zones'][0]
    assert zone['status'] == 'WAIT'
    assert zone['lifecycle_state'] == expected
    assert zone['alert_allowed'] is False
    assert diagnostic['contract_blocks'][0]['lifecycle_state'] == expected

def test_blocked_confirmed_plan_removed():
    original = _analysis(status='CONFIRMED') + '\n```trade_plan\n{"status":"ENTRY_READY"}\n```'
    updated, _ = apply_zone_lifecycle(original, _kwargs([102.0, 103.0]))
    assert validate_analysis(updated) == 'WAIT'
    assert extract_json_block(updated, 'trade_plan') is None

def test_unknown_state_not_silently_accepted():
    with pytest.raises(RuntimeError):
        validate_analysis(_analysis(status='WAIT').replace('"status": "WAIT"', '"status": "UNKNOWN"'))

def test_contract_adapter_preserves_terminal_evidence():
    watch = {'zones': [{'status': 'INVALIDATED', 'direction': 'SELL'}]}
    text, blocked = normalize_lifecycle_contract('状态：APPROACH', watch)
    assert text == '状态：WAIT'
    assert blocked and watch['zones'][0]['lifecycle_state'] == 'INVALIDATED'
