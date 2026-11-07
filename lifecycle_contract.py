"""Conservative compatibility boundary; not a complete scenario state machine."""
import re

BLOCKED = {'BROKEN', 'INVALIDATED', 'PAUSED', 'EXPIRED'}

def normalize_lifecycle_contract(text, watch):
    blocked = []
    approach = False
    for index, zone in enumerate(watch.get('zones', [])):
        if not isinstance(zone, dict):
            continue
        state = zone.get('status')
        if state in BLOCKED:
            zone['lifecycle_state'] = state
            zone['scenario_state'] = 'INVALIDATED' if state == 'INVALIDATED' else 'PAUSED'
            zone['status'] = 'WAIT'
            zone['alert_allowed'] = False
            blocked.append({'zone_index': index, 'lifecycle_state': state})
        elif state == 'APPROACH':
            approach = True
    if blocked:
        # Conservative whole-analysis suppression until per-scenario readiness is unified.
        for zone in watch.get('zones', []):
            if isinstance(zone, dict):
                zone['status'] = 'WAIT'
                zone['alert_allowed'] = False
        unified = 'WAIT'
    elif approach:
        unified = 'APPROACH'
    else:
        unified = 'WAIT'
    text = re.sub(r'(?m)^(\s*(?:\*\*)?状态\s*[:：]\s*)(WAIT|APPROACH|CONFIRMED)\b', r'\g<1>' + unified, text)
    if blocked:
        text = re.sub(r'```\s*trade_plan\b.*?```', '', text, flags=re.S)
    return text, blocked
