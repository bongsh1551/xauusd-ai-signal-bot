"""Zone lifecycle and stable scenario identity for XAUUSD market_watch.

The model may identify a zone, but it may not decide that an old supply zone
remains actionable after price has closed through it.  This module enforces a
conservative lifecycle for SELL zones before the analysis is validated.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _zone_bounds(zone: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    low, high = zone.get("low"), zone.get("high")
    if not _finite(low) or not _finite(high) or low > high:
        return None
    return float(low), float(high)


def _atr(values: List[float], period: int = 14) -> Optional[float]:
    if len(values) < period + 1:
        return None
    trs = []
    for index in range(1, len(values)):
        trs.append(abs(values[index] - values[index - 1]))
    sample = trs[-period:]
    return sum(sample) / len(sample) if sample else None


def _m5_series_from_parts(parts: List[Dict[str, Any]]) -> Tuple[List[float], List[float]]:
    """Extract M5 close prices and true ranges from the AI input text."""
    closes: List[float] = []
    ranges: List[float] = []
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
            ranges.append(high - low)
    return closes, ranges


def _stable_scenario_id(zone: Dict[str, Any]) -> Optional[str]:
    direction = zone.get("direction")
    timeframe = zone.get("timeframe") or zone.get("zone_timeframe") or "unspecified"
    origin = zone.get("origin_candle_time") or zone.get("origin_time")
    if direction not in ("BUY", "SELL") or not isinstance(origin, str) or not origin.strip():
        return None
    return f"{direction}:{timeframe}:{origin.strip()}"


def _replace_market_watch_block(text: str, watch: Dict[str, Any]) -> str:
    pattern = re.compile(r"```market_watch\s*\n.*?\n```", re.DOTALL)
    replacement = "```market_watch\n" + json.dumps(watch, ensure_ascii=False, indent=2) + "\n```"
    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise RuntimeError("zone lifecycle: market_watch block not found")
    return updated


def apply_zone_lifecycle(text: str, kwargs: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Apply conservative SELL-zone lifecycle rules to the model output.

    Returns the updated analysis text and a diagnostic record.  It never creates
    a new zone, never turns WAIT into APPROACH, and never enables an entry.
    """
    parts = (((kwargs.get("json") or {}).get("contents") or [{}])[0].get("parts") or [])
    closes, ranges = _m5_series_from_parts(parts)
    if not closes:
        raise RuntimeError("zone lifecycle: M5 closes unavailable")
    latest_close = closes[-1]
    atr = _atr(ranges)
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

    changes = []
    for zone in watch["zones"]:
        if not isinstance(zone, dict):
            continue
        if zone.get("direction") != "SELL":
            continue
        scenario_id = _stable_scenario_id(zone)
        if scenario_id:
            zone["scenario_id"] = scenario_id
        else:
            zone["status"] = "WAIT"
            zone["lifecycle_reason"] = "MISSING_STABLE_SCENARIO_ID"
            changes.append({"action": "WAIT", "reason": "missing origin/timeframe"})
            continue

        bounds = _zone_bounds(zone)
        if bounds is None:
            zone["status"] = "WAIT"
            zone["lifecycle_reason"] = "INVALID_ZONE_BOUNDS"
            changes.append({"action": "WAIT", "reason": "invalid bounds"})
            continue
        low, high = bounds
        invalidation_price = high + buffer
        zone["invalidation_price"] = invalidation_price
        prior_status = zone.get("status")

        if prior_status == "INVALIDATED":
            zone["status"] = "INVALIDATED"
            zone["alert_allowed"] = False
            changes.append({"action": "KEEP_INVALIDATED", "scenario_id": scenario_id})
            continue

        closes_above = sum(1 for close in closes[-2:] if close > invalidation_price)
        if closes_above >= 2:
            zone["status"] = "INVALIDATED"
            zone["close_through"] = True
            zone["alert_allowed"] = False
            zone["lifecycle_reason"] = "TWO_M5_CLOSES_ABOVE_SUPPLY"
            changes.append({"action": "INVALIDATED", "scenario_id": scenario_id})
        elif closes_above == 1:
            zone["status"] = "BROKEN"
            zone["close_through"] = True
            zone["alert_allowed"] = False
            zone["lifecycle_reason"] = "ONE_M5_CLOSE_ABOVE_SUPPLY"
            changes.append({"action": "BROKEN", "scenario_id": scenario_id})
        else:
            zone["close_through"] = False
            if prior_status == "APPROACH":
                zone["status"] = "WAIT"
                zone["lifecycle_reason"] = "LIFECYCLE_REQUIRES_CODE_CONFIRMATION"
                changes.append({"action": "DOWNGRADED_TO_WAIT", "scenario_id": scenario_id})

    updated_text = _replace_market_watch_block(text, watch)
    diagnostic = {
        "latest_m5_close": latest_close,
        "atr": atr,
        "invalidation_buffer": buffer,
        "changes": changes,
    }
    return updated_text, diagnostic
