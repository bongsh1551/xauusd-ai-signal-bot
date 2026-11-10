"""Full-input Groq Qwen vision validation using production charts/context; no publication."""
import base64
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ANALYSIS_MODE", "manual_signals")
os.environ.setdefault("MARKET_MEMORY_MODE", "manual_signals")

import main as pipeline
import daily_memory
import sensenova_runner as contract
from fundamentals import collect_fundamentals

MODEL = "qwen/qwen3.8-27b"
ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"


def main():
    twelve_key = os.environ.get("TWELVEDATA_API_KEY", "").strip()
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not twelve_key or not groq_key:
        raise RuntimeError("TWELVEDATA_API_KEY and GROQ_API_KEY are required")

    now = pd.Timestamp.now(tz="UTC")
    local_now = now.tz_convert("Asia/Kuala_Lumpur")
    if local_now.dayofweek >= 5 or not (8 <= local_now.hour < 23):
        raise RuntimeError("Full live-input validation is restricted to weekdays 08:00-23:00 MYT")

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

    with tempfile.TemporaryDirectory(prefix="goldscalp_groq_validation_") as temp:
        work = Path(temp)
        folder = work / "journal" / (now.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
        folder.mkdir(parents=True)
        old_cwd = Path.cwd()
        os.chdir(work)
        os.environ["ZONE_LIFECYCLE_STATE_PATH"] = str(work / "zone_lifecycle_state.json")
        try:
            content = [
                {"type": "text", "text": instruction},
                {"type": "text", "text": "【DAILY MARKET MEMORY｜24小时连续上下文】\n" + memory_context},
            ]
            charts = []
            m5_diagnostic = None
            image_bytes_list = []
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
                content.append({"type": "text", "text": chart_text})
                image_bytes_list.append(image_bytes)
                content.append({"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
                }})

            fundamentals = collect_fundamentals(twelve_key, now, folder)
            content.append({"type": "text", "text": fundamentals["context"]})

            image_sizes = [len(item) for item in image_bytes_list]
            print("GROQ_INPUT_DIAGNOSTIC=" + json.dumps({
                "model": MODEL,
                "image_count": len(image_bytes_list),
                "image_bytes": image_sizes,
                "image_total_bytes": sum(image_sizes),
                "chart_candles": {item["interval"]: item.get("candles_sent") for item in charts},
                "memory_status": memory_status,
                "fundamentals_context_characters": len(fundamentals["context"]),
                "prompt_characters": len(instruction),
            }, ensure_ascii=False, sort_keys=True), flush=True)

            response = requests.post(
                ENDPOINT,
                headers={"Authorization": "Bearer " + groq_key, "Content-Type": "application/json"},
                json={
                    "model": MODEL,
                    "messages": [{"role": "user", "content": content}],
                    "temperature": 0.2,
                    "max_completion_tokens": 2048,
                    "stream": False,
                },
                timeout=(15, 180),
                allow_redirects=False,
            )
            print("HTTP_STATUS=" + str(response.status_code), flush=True)
            if response.status_code >= 400:
                try:
                    error = response.json().get("error", {})
                    print("GROQ_ERROR=" + json.dumps({
                        "type": error.get("type") if isinstance(error, dict) else None,
                        "code": error.get("code") if isinstance(error, dict) else None,
                        "message": str(error.get("message", ""))[:700] if isinstance(error, dict) else "unknown",
                    }, ensure_ascii=False), flush=True)
                except Exception:
                    print("GROQ_ERROR=non-JSON response", flush=True)
                return 20

            result = response.json()
            choices = result.get("choices") or []
            if not choices or not isinstance(choices[0], dict):
                raise RuntimeError("Groq returned no valid choice")
            choice = choices[0]
            message = choice.get("message") or {}
            analysis = message.get("content")
            if not isinstance(analysis, str) or not analysis.strip():
                raise RuntimeError("Groq returned empty/non-text final content")
            finish = choice.get("finish_reason")
            usage = result.get("usage") or {}
            if finish != "stop":
                raise RuntimeError("Groq response incomplete: finish_reason=" + str(finish))

            # Apply the existing strict output contract; no lifecycle persistence/publication.
            status = contract.validate_analysis(analysis)
            watch = pipeline.extract_json_block(analysis, "market_watch")
            plan = pipeline.extract_json_block(analysis, "trade_plan")
            if not isinstance(watch, dict) or not isinstance(watch.get("zones"), list):
                raise RuntimeError("market_watch schema validation failed")

            summary = {
                "result": "PASS_GROQ_FULL_INPUT_AND_SCHEMA_VALIDATION",
                "publication": "DISABLED_BY_TEST",
                "model": result.get("model", MODEL),
                "finish_reason": finish,
                "analysis_status": status,
                "final_output_characters": len(analysis),
                "market_watch_zones": len(watch["zones"]),
                "trade_plan_present": isinstance(plan, dict),
                "chart_candles": {item["interval"]: item.get("candles_sent") for item in charts},
                "chart_quality_flags": {item["interval"]: item.get("quality_review_required") for item in charts},
                "data_quality_gate_passed": bool(m5_diagnostic) and not m5_diagnostic.get("timestamp_stale")
                    and not any(item.get("quality_review_required") for item in charts),
                "usage": {key: usage.get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                          if usage.get(key) is not None},
            }
            print("GROQ_FULL_VALIDATION=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
            print("RESULT=PASS_GROQ_FULL_INPUT_AND_SCHEMA_VALIDATION")
            print("NOTICE=No Telegram, Cloudflare ingest, publication, or automatic order was executed.")
            return 0
        finally:
            os.chdir(old_cwd)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        import traceback
        print("RESULT=FAIL_GROQ_FULL_INPUT_VALIDATION")
        print("ERROR=" + (str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)[:700])
        traceback.print_exc()
        sys.exit(1)
