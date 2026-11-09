"""Zone lifecycle and proximity alerts for human-reviewed XAUUSD setups.

APPROACH is an early zone-proximity warning, not an entry confirmation. M5
confirmation and the separate entry review gate remain required for ENTRY_READY.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from lifecycle_contract import normalize_lifecycle_contract


def _state_path() -> Path:
    return Path(os.getenv('ZONE_LIFECYCLE_STATE_PATH', '.cache/zone_lifecycle_state.json'))


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _zone_bounds(zone: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    low, high = zone.get("low"), zone.get("high")
    if not _finite(low) or not _finite(high) or low > high:
        return None
    return float(low), float(high)


def _atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    trs = []
    for index in range(1, len(closes)):
        high, low, previous_close = highs[index], lows[index], closes[index - 1]
        trs.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    sample = trs[-period:]
    return sum(sample) / len(sample) if sample else None


def _m5_series_from_parts(parts: List[Dict[str, Any]]) -> Tuple[List[float], List[float], List[float]]:
    closes: List[float] = []
    highs: List[float] = []
    lows: List[float] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if not isinstance(text, str) or "5min 已收线 OHLC" not in text:
            continue
        for line in text.splitlines():
            fields = line.split(",")
            if len(fields) < 5:
                continue
            try:
                open_price, high, low, close = (float(fields[1]), float(fields[2]),
                                                float(fields[3]), float(fields[4]))
            except (TypeError, ValueError):
                continue
            closes.append(close)
            highs.append(high)
            lows.append(low)
    return closes, highs, lows


def _stable_scenario_id(zone: Dict[str, Any]) -> Optional[str]:
    direction = zone.get("direction")
    timeframe = zone.get("source_interval") or zone.get("timeframe") or zone.get("zone_timeframe") or "unspecified"
    origin = zone.get("source_candle_utc") or zone.get("origin_candle_time") or zone.get("origin_time")
    if direction not in ("BUY", "SELL") or not isinstance(origin, str) or not origin.strip():
        return None
    return f"{direction}:{timeframe}:{origin.strip()}"


def _load_invalidated() -> Dict[str, Any]:
    try:
        value = json.loads(_state_path().read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_invalidated(states: Dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(states, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
    temporary.replace(path)


def _replace_market_watch_block(text: str, watch: Dict[str, Any]) -> str:
    pattern = re.compile(r"```market_watch\s*\n.*?\n```", re.DOTALL)
    replacement = "```market_watch\n" + json.dumps(watch, ensure_ascii=False, indent=2) + "\n```"
    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise RuntimeError("zone lifecycle: market_watch block not found")
    return updated


def _fundamental_context(watch: Dict[str, Any], zone: Dict[str, Any]) -> Dict[str, Any]:
    source = zone if all(k in zone for k in ("news_bias", "currency_strength", "calendar_risk", "fundamental_note")) else watch
    return {
        "news_bias": source.get("news_bias"),
        "currency_strength": source.get("currency_strength"),
        "calendar_risk": source.get("calendar_risk"),
        "fundamental_note": source.get("fundamental_note"),
    }


def apply_zone_lifecycle(text: str, kwargs: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    parts = (((kwargs.get("json") or {}).get("contents") or [{}])[0].get("parts") or [])
    closes, highs, lows = _m5_series_from_parts(parts)
    if not closes:
        raise RuntimeError("zone lifecycle: M5 closes unavailable")
    latest_close = closes[-1]
    atr = _atr(highs, lows, closes)
    buffer = 0.25 * atr if atr and atr > 0 else 0.0

    match = re.search(r"```market_watch\s*\n(\{.*?\})\s*\n```", text, re.DOTALL)
    if not match:
        raise RuntimeError("zone lifecycle: market_watch block missing")
    try:
        watch = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError("zone lifecycle: invalid market_watch JSON") from exc
    if not isinstance(watch, dict) or not isinstance(watch.get("zones"), list):
        raise RuntimeError("zone lifecycle: market_watch zones missing")

    persisted = _load_invalidated()
    changed = False
    changes = []
    for zone in watch["zones"]:
        if not isinstance(zone, dict):
            continue
        direction = zone.get("direction")
        if direction not in ("BUY", "SELL"):
            continue
        scenario_id = _stable_scenario_id(zone)
        if scenario_id:
            zone["scenario_id"] = scenario_id
        else:
            zone["status"] = "WAIT"
            zone["lifecycle_reason"] = "MISSING_STABLE_SCENARIO_ID"
            changes.append({"action": "WAIT", "reason": "missing origin/timeframe"})
            continue

        if persisted.get(scenario_id) == 'INVALIDATED':
            zone["status"] = "INVALIDATED"
            zone["alert_allowed"] = False
            zone["lifecycle_reason"] = "PRIOR_INVALIDATION_PERSISTED"
            changes.append({"action": "KEEP_INVALIDATED", "scenario_id": scenario_id})
            continue

        bounds = _zone_bounds(zone)
        if bounds is None:
            zone["status"] = "WAIT"
            zone["lifecycle_reason"] = "INVALID_ZONE_BOUNDS"
            changes.append({"action": "WAIT", "reason": "invalid bounds"})
            continue
        low, high = bounds
        if direction == "SELL":
            invalidation_price = high + buffer
        else:
            invalidation_price = low - buffer
        zone["invalidation_price"] = invalidation_price
        prior_status = zone.get("status")

        if prior_status == "INVALIDATED":
            zone["status"] = "INVALIDATED"
            zone["alert_allowed"] = False
            persisted[scenario_id] = 'INVALIDATED'
            changed = True
            changes.append({"action": "KEEP_INVALIDATED", "scenario_id": scenario_id})
            continue

        if direction == "SELL":
            closes_through = sum(1 for close in closes[-2:] if close > invalidation_price)
            broken_reason = "ONE_M5_CLOSE_ABOVE_SUPPLY"
            invalidated_reason = "TWO_M5_CLOSES_ABOVE_SUPPLY"
        else:
            closes_through = sum(1 for close in closes[-2:] if close < invalidation_price)
            broken_reason = "ONE_M5_CLOSE_BELOW_DEMAND"
            invalidated_reason = "TWO_M5_CLOSES_BELOW_DEMAND"

        if closes_through >= 2:
            zone["status"] = "INVALIDATED"
            zone["close_through"] = True
            zone["alert_allowed"] = False
            zone["lifecycle_reason"] = invalidated_reason
            persisted[scenario_id] = 'INVALIDATED'
            changed = True
            changes.append({"action": "INVALIDATED", "scenario_id": scenario_id})
            continue
        if closes_through == 1:
            zone["status"] = "BROKEN"
            zone["close_through"] = True
            zone["alert_allowed"] = False
            zone["lifecycle_reason"] = broken_reason
            changes.append({"action": "BROKEN", "scenario_id": scenario_id})
            continue

        zone["close_through"] = False
        # APPROACH is a proximity heads-up only. Do not require the entry
        # confirmation stack or complete fundamental fields before warning.
        # The separate scenario review gate still controls ENTRY_READY.
        distance = max(buffer, 0.50)
        near_zone = (low - distance) <= latest_close <= (high + distance)
        if near_zone:
            zone["status"] = "APPROACH"
            zone["alert_allowed"] = True
            zone["lifecycle_reason"] = "PRICE_APPROACHING_VALID_ZONE"
            zone["distance_to_zone"] = round(max(low-latest_close, latest_close-high, 0.0), 3)
            zone["missing_confirmations"] = [key for key in ("sweep", "rejection", "displacement", "mss")
                                             if not (zone.get("confirmations") or {}).get(key)]
            changes.append({"action": "APPROACH", "scenario_id": scenario_id})
        else:
            zone["status"] = "WAIT"
            zone["alert_allowed"] = False
            zone["lifecycle_reason"] = "PRICE_NOT_NEAR_ZONE"
            zone["distance_to_zone"] = round(max(low-latest_close, latest_close-high, 0.0), 3)
            changes.append({"action": "WAIT", "reason": "price not near zone"})

    if changed:
        _save_invalidated(persisted)
    text, contract_blocks = normalize_lifecycle_contract(text, watch)
    updated_text = _replace_market_watch_block(text, watch)
    diagnostic = {
        "latest_m5_close": latest_close,
        "atr": atr,
        "invalidation_buffer": buffer,
        "changes": changes,
        "contract_blocks": contract_blocks,
        "persisted_invalidations": sorted(persisted),
    }
    return updated_text, diagnostic
