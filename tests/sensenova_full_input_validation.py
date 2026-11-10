"""Full live-input SenseNova Instruct validation; never publishes or mutates market memory."""
import base64
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ANALYSIS_MODE", "manual_signals")
os.environ.setdefault("MARKET_MEMORY_MODE", "manual_signals")

import main as pipeline
import daily_memory
import sensenova_runner as runner
from fundamentals import collect_fundamentals


def main():
    twelve_key = os.environ.get("TWELVEDATA_API_KEY", "").strip()
    sense_key = os.environ.get("SENSENOVA_API_KEY", "").strip()
    if not twelve_key or not sense_key:
        raise RuntimeError("TWELVEDATA_API_KEY and SENSENOVA_API_KEY are required")

    now = pd.Timestamp.now(tz="UTC")
    local_now = now.tz_convert("Asia/Kuala_Lumpur")
    if local_now.dayofweek >= 5 or not (8 <= local_now.hour < 23):
        raise RuntimeError("Full live-input validation is restricted to weekdays 08:00-23:00 MYT")

    # Read cached market memory without changing it. FX cache writes are isolated
    # in the temporary working directory and discarded after this validation.
    memory_path = ROOT / ".cache" / "daily_market_memory.json"
    memory_state, memory_status = daily_memory.load_state(
        memory_path, now.to_pydatetime(), "manual_signals"
    )
    memory_context = daily_memory.context_text(memory_state, now.to_pydatetime())
    if memory_state.get("opening_plan") is None:
        memory_context += (
            "\nNo opening plan exists for the current MYT date. Establish a fresh "
            "opening context today; prior_session_context is reference only."
        )

    prompt = (ROOT / pipeline.PROMPT_PATH).read_text(encoding="utf-8").strip()
    if not prompt:
        raise RuntimeError("GoldScalp production prompt is empty")

    instruction = (
        prompt
        + "\n\n【执行模式】实时手动信号模式：每轮分析最新已收线行情，按证据输出 WAIT、APPROACH 或 CONFIRMED；满足条件时发布 ENTRY_READY 参考计划。只提供人工决策参考，绝不自动下单。\n"
        + pipeline.HEADER
        + "\n当前 UTC：" + now.isoformat()
        + "\n当前大马时间：" + local_now.isoformat()
        + "\n不编造宏观背景，不把新时间戳等同于有效行情。只基于以下输入。"
    )

    with tempfile.TemporaryDirectory(prefix="goldscalp_full_validation_") as temp:
        work = Path(temp)
        folder = work / "journal" / (now.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
        folder.mkdir(parents=True)
        old_cwd = Path.cwd()
        os.chdir(work)
        os.environ["ZONE_LIFECYCLE_STATE_PATH"] = str(work / "zone_lifecycle_state.json")
        try:
            common_parts = [
                {"text": instruction},
                {"text": "【DAILY MARKET MEMORY｜24小时连续上下文】\n" + memory_context},
            ]
            image_pairs = []
            charts = []
            m5_diagnostic = None

            # Same chart fetcher, 40 closed OHLC rows, diagnostics and 120-candle
            # chart images as the production analysis pipeline.
            for interval, minutes in (("5min", 5), ("15min", 15), ("1h", 60)):
                frame, image_bytes, diagnostic = pipeline.fetch_chart(
                    twelve_key, interval, minutes, now, folder
                )
                charts.append(diagnostic)
                if interval == "5min":
                    m5_diagnostic = diagnostic
                chart_text = (
                    interval + " 已收线 OHLC，UTC：\n"
                    + frame.tail(40).to_csv(index_label="timestamp_utc")
                    + "\n程序诊断：" + json.dumps(diagnostic, ensure_ascii=False)
                )
                png_image = (folder / f"{interval}.png").read_bytes()
                image_pairs.append({
                    "interval": interval,
                    "png": png_image,
                    "webp": image_bytes,
                })
                common_parts.append({"text": chart_text})

            fundamentals = collect_fundamentals(twelve_key, now, folder)
            common_parts.append({"text": fundamentals["context"]})

            # Identical text, OHLC, memory, fundamentals and chart pixels;
            # only the image encoding/MIME differs between the two API calls.
            variants = {}
            for image_format in ("png", "webp"):
                parts = list(common_parts)
                for pair in image_pairs:
                    image_bytes = pair[image_format]
                    parts.append({"inline_data": {
                        "mime_type": "image/" + image_format,
                        "data": base64.b64encode(image_bytes).decode("ascii"),
                    }})
                variant_summary = {
                    "image_format": image_format,
                    "image_bytes": {p["interval"]: len(p[image_format]) for p in image_pairs},
                    "image_total_bytes": sum(len(p[image_format]) for p in image_pairs),
                    "result": "NOT_RUN",
                }
                try:
                    adapted = runner.post(
                        "https://generativelanguage.googleapis.com/v1beta/models/"
                        + runner.MODEL + ":generateContent",
                        headers={"x-goog-api-key": sense_key},
                        json={"contents": [{"role": "user", "parts": parts}],
                              "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048}},
                        timeout=(10, 120),
                    )
                    result = adapted.json()
                    candidates = result.get("candidates") or []
                    if not candidates:
                        raise RuntimeError("SenseNova adapter returned no candidate")
                    candidate = candidates[0]
                    analysis = "\n".join(
                        item.get("text", "")
                        for item in candidate.get("content", {}).get("parts", [])
                        if isinstance(item, dict) and isinstance(item.get("text"), str)
                    ).strip()
                    if candidate.get("finishReason") != "STOP" or not analysis:
                        raise RuntimeError("SenseNova full-input response incomplete")
                    analysis_status = runner.validate_analysis(analysis)
                    trade_plan = pipeline.extract_json_block(analysis, "trade_plan")
                    market_watch = pipeline.extract_json_block(analysis, "market_watch")
                    if not isinstance(market_watch, dict) or not isinstance(market_watch.get("zones"), list):
                        raise RuntimeError("market_watch schema validation failed")
                    diagnostic = dict(runner.LAST_DIAGNOSTIC)
                    variant_summary.update({
                        "result": "PASS",
                        "analysis_status": analysis_status,
                        "market_watch_zones": len(market_watch["zones"]),
                        "trade_plan_present": isinstance(trade_plan, dict),
                        "token_usage": diagnostic.get("usage", {}),
                        "finish_reason": diagnostic.get("finish_reason"),
                    })
                except Exception as exc:
                    variant_summary.update({
                        "result": "FAIL",
                        "error": (str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)[:500],
                        "diagnostic": dict(runner.LAST_DIAGNOSTIC),
                    })
                variants[image_format] = variant_summary

            png_ok = variants["png"]["result"] == "PASS"
            webp_ok = variants["webp"]["result"] == "PASS"
            summary = {
                "result": "PASS_BOTH_ENCODINGS" if png_ok and webp_ok else "PARTIAL_OR_FAILED",
                "publication": "DISABLED_BY_TEST",
                "model": runner.MODEL,
                "profile": os.environ.get("SENSENOVA_API_PROFILE", "instruct"),
                "market_memory_status": memory_status,
                "chart_dimensions_max_edge": 2048,
                "chart_candles": {item["interval"]: item.get("candles_sent") for item in charts},
                "chart_quality_flags": {item["interval"]: item.get("quality_review_required") for item in charts},
                "variants": variants,
                "data_quality_gate_passed": not any(item.get("quality_review_required") for item in charts),
                "live_publication_ready": False,
                "same_market_input_for_both": True,
            }
            print("GOLDSCALP_WEBP_AB_VALIDATION=" + json.dumps(
                summary, ensure_ascii=False, sort_keys=True
            ))
            print("RESULT=" + summary["result"])
            print("NOTICE=No Telegram, Cloudflare ingest, publication, or automatic order was executed.")
            return 0 if png_ok and webp_ok else 1
        finally:
            os.chdir(old_cwd)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        import traceback
        print("RESULT=FAIL_FULL_INPUT_VALIDATION")
        print("ERROR=" + (str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)[:700])
        traceback.print_exc()
        sys.exit(1)
