#!/usr/bin/env python3
"""Read-only XAU/USD M5 historical export from Twelve Data.

Uses existing GitHub Actions secrets. Never prints API keys or request URLs.
One time_series request per 14-day UTC window; no production services are touched.
"""
import argparse
import csv
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

API_URL = "https://api.twelvedata.com/time_series"
INTERVAL = "5min"
SYMBOL = "XAU/USD"
MAX_RECORDS_PER_CALL = 5000
SAFE_REQUEST_CAP = 700
REQUEST_SPACING_SECONDS = 8.2


def parse_date(value, end=False):
    if not value:
        return datetime.now(timezone.utc).replace(microsecond=0) if end else datetime(2020, 1, 1, tzinfo=timezone.utc)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def iso_api(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def valid_bar(item):
    try:
        stamp = datetime.fromisoformat(str(item["datetime"]).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        stamp = stamp.astimezone(timezone.utc)
        o, h, l, c = (float(item[k]) for k in ("open", "high", "low", "close"))
        if not all(0 < x < float("inf") for x in (o, h, l, c)):
            return None
        if h < max(o, c, l) or l > min(o, c, h):
            return None
        return (stamp.isoformat(), o, h, l, c)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default=os.getenv("START_DATE", "2020-01-01"))
    parser.add_argument("--end-date", default=os.getenv("END_DATE", ""))
    parser.add_argument("--max-requests", type=int, default=SAFE_REQUEST_CAP)
    parser.add_argument("--chunk-days", type=int, default=14)
    parser.add_argument("--output-dir", default="export")
    args = parser.parse_args()

    keys = [os.getenv("TWELVEDATA_API_KEY", "").strip(),
            os.getenv("TWELVEDATA_API_KEY_2", "").strip()]
    keys = [k for k in keys if k]
    if not keys:
        raise RuntimeError("No Twelve Data key configured in GitHub Actions secrets.")
    if not 1 <= args.max_requests <= SAFE_REQUEST_CAP:
        raise ValueError(f"max-requests must be between 1 and {SAFE_REQUEST_CAP}")
    if not 1 <= args.chunk_days <= 14:
        raise ValueError("chunk-days must be between 1 and 14")

    start = parse_date(args.start_date)
    end = parse_date(args.end_date, end=True)
    if start >= end:
        raise ValueError("start-date must be earlier than end-date")

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "XAUUSD_TwelveData_M5.csv"
    manifest_path = out / "manifest.json"
    rows = {}
    request_count = 0
    successful_windows = 0
    empty_windows = 0
    errors = []
    last_request_at = 0.0
    quota_left_values = []

    cursor = start
    while cursor < end and request_count < args.max_requests:
        window_end = min(cursor + timedelta(days=args.chunk_days) - timedelta(seconds=1), end)
        params_base = {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "start_date": iso_api(cursor),
            "end_date": iso_api(window_end),
            "timezone": "UTC",
            "order": "ASC",
            "format": "JSON",
        }
        payload = None
        last_error = None
        for key_index, key in enumerate(keys):
            wait = REQUEST_SPACING_SECONDS - (time.monotonic() - last_request_at)
            if wait > 0:
                time.sleep(wait)
            params = dict(params_base)
            params["apikey"] = key
            request_count += 1
            try:
                response = requests.get(API_URL, params=params, timeout=(15, 90))
                last_request_at = time.monotonic()
                left = response.headers.get("api-credits-left")
                if left is not None:
                    try:
                        quota_left_values.append(int(left))
                    except ValueError:
                        pass
                if response.status_code == 429:
                    last_error = "HTTP_429_RATE_OR_DAILY_LIMIT"
                    # Basic plan quota is 8 credits/minute and 800/day.
                    # Wait for the minute reset once, then retry the same key.
                    if request_count < args.max_requests:
                        time.sleep(62)
                        wait = REQUEST_SPACING_SECONDS - (time.monotonic() - last_request_at)
                        if wait > 0:
                            time.sleep(wait)
                        request_count += 1
                        response = requests.get(API_URL, params=params, timeout=(15, 90))
                        last_request_at = time.monotonic()
                    if response.status_code == 429:
                        raise RuntimeError("Twelve Data returned 429 after one minute-reset retry.")
                response.raise_for_status()
                body = response.json()
                if body.get("status") != "ok" or not isinstance(body.get("values"), list):
                    message = body.get("message") or body.get("code") or body.get("status") or "UNKNOWN_API_ERROR"
                    raise RuntimeError("Twelve Data rejected request: " + str(message)[:220])
                meta = body.get("meta", {})
                if meta.get("symbol") and meta.get("symbol") != SYMBOL:
                    raise RuntimeError("Unexpected symbol returned by Twelve Data.")
                if meta.get("interval") and meta.get("interval") != INTERVAL:
                    raise RuntimeError("Unexpected interval returned by Twelve Data.")
                if len(body["values"]) > MAX_RECORDS_PER_CALL:
                    raise RuntimeError("Response exceeded the 5000-record safety ceiling.")
                payload = body
                break
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {str(exc)[:220]}"
                if "429" in last_error or "rate" in last_error.lower():
                    # Do not burn through both keys rapidly on a shared account quota.
                    break
                if key_index == len(keys) - 1:
                    break

        if payload is None:
            errors.append({"start_utc": iso_api(cursor), "end_utc": iso_api(window_end),
                           "error": last_error or "UNKNOWN_ERROR"})
            # Fail closed: do not skip a failed time window and claim full coverage.
            break

        values = payload["values"]
        accepted = 0
        rejected = 0
        for item in values:
            bar = valid_bar(item)
            if bar is None:
                rejected += 1
                continue
            rows[bar[0]] = bar[1:]
            accepted += 1
        if accepted:
            successful_windows += 1
        else:
            empty_windows += 1
        print(f"window={iso_api(cursor)}..{iso_api(window_end)} rows={accepted} rejected={rejected} requests={request_count}")
        cursor = window_end + timedelta(seconds=1)

    ordered = sorted(rows.items(), key=lambda x: x[0])
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp_utc", "open", "high", "low", "close"])
        for stamp, values in ordered:
            writer.writerow([stamp, *values])

    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    manifest = {
        "provider": "Twelve Data",
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "timezone": "UTC",
        "requested_start_utc": iso_api(start),
        "requested_end_utc": iso_api(end),
        "completed_through_utc": iso_api(cursor - timedelta(seconds=1)) if cursor > start else None,
        "complete": cursor >= end and not errors,
        "requests_used_by_export": request_count,
        "safe_request_cap": args.max_requests,
        "chunk_days": args.chunk_days,
        "successful_windows": successful_windows,
        "empty_windows": empty_windows,
        "rows": len(ordered),
        "first_bar_utc": ordered[0][0] if ordered else None,
        "last_bar_utc": ordered[-1][0] if ordered else None,
        "duplicate_timestamps_after_dedup": 0,
        "invalid_ohlc_rows_rejected": None,
        "quota_left_observed_min": min(quota_left_values) if quota_left_values else None,
        "errors": errors,
        "csv_sha256": digest,
        "csv_file": csv_path.name,
        "note": "Twelve Data XAU/USD is a separate feed from GApps/RealMarketAPI until OHLC alignment is proven."
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if errors or not manifest["complete"]:
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"EXPORT_FAILED: {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
        sys.exit(1)
