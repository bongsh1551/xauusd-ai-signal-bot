"""Identical-input Groq PNG vs WEBP A/B; no publication or memory mutation."""
import base64, json, os, sys, tempfile, uuid, time
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
    td = os.environ.get("TWELVEDATA_API_KEY", "").strip()
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not td or not key:
        raise RuntimeError("TWELVEDATA_API_KEY and GROQ_API_KEY are required")
    now = pd.Timestamp.now(tz="UTC")
    local = now.tz_convert("Asia/Kuala_Lumpur")
    if local.dayofweek >= 5 or not (8 <= local.hour < 23):
        raise RuntimeError("Restricted to weekdays 08:00-23:00 MYT")
    memory, memory_status = daily_memory.load_state(
        ROOT / ".cache" / "daily_market_memory.json", now.to_pydatetime(), "manual_signals")
    memory_text = daily_memory.context_text(memory, now.to_pydatetime())
    if memory.get("opening_plan") is None:
        memory_text += "\nNo opening plan exists for current MYT date; establish fresh opening context."
    prompt = (ROOT / pipeline.PROMPT_PATH).read_text(encoding="utf-8").strip()
    instruction = (prompt + "\n\n【执行模式】实时手动信号模式：按证据输出 WAIT、APPROACH 或 CONFIRMED；只供人工决策，绝不自动下单。\n"
        + pipeline.HEADER + "\n当前 UTC：" + now.isoformat() + "\n当前大马时间：" + local.isoformat()
        + "\n不编造宏观背景，只基于以下输入。")
    with tempfile.TemporaryDirectory(prefix="groq_webp_ab_") as temp:
        work = Path(temp); folder = work / "journal" / (now.strftime("%Y%m%d-%H%M%S")+"-"+uuid.uuid4().hex[:8])
        folder.mkdir(parents=True); old = Path.cwd(); os.chdir(work)
        os.environ["ZONE_LIFECYCLE_STATE_PATH"] = str(work / "zone_lifecycle_state.json")
        try:
            charts, pairs, m5 = [], [], None
            for interval, minutes in (("5min",5),("15min",15),("1h",60)):
                frame, webp, diag = pipeline.fetch_chart(td, interval, minutes, now, folder)
                charts.append(diag)
                if interval == "5min": m5 = diag
                text = interval + " 已收线 OHLC，UTC：\n" + frame.tail(40).to_csv(index_label="timestamp_utc") + "\n程序诊断：" + json.dumps(diag, ensure_ascii=False)
                pairs.append({"interval":interval,"text":text,"png":(folder/f"{interval}.png").read_bytes(),"webp":webp})
            fundamentals = collect_fundamentals(td, now, folder)["context"]
            variants = {}
            for fmt in ("png","webp"):
                content = [{"type":"text","text":instruction},
                    {"type":"text","text":"【DAILY MARKET MEMORY｜24小时连续上下文】\n"+memory_text}]
                for pair in pairs:
                    raw = pair[fmt]
                    content.extend([{"type":"text","text":pair["text"]},
                        {"type":"image_url","image_url":{"url":"data:image/"+fmt+";base64,"+base64.b64encode(raw).decode("ascii")}}])
                content.append({"type":"text","text":fundamentals})
                item = {"image_format":fmt,"image_bytes":{p["interval"]:len(p[fmt]) for p in pairs},
                    "image_total_bytes":sum(len(p[fmt]) for p in pairs),"result":"NOT_RUN"}
                started = time.monotonic()
                try:
                    response = requests.post(ENDPOINT,
                        headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},
                        json={"model":MODEL,"messages":[{"role":"user","content":content}],
                              "temperature":0.2,"max_completion_tokens":2048,"stream":False},
                        timeout=(15,180),allow_redirects=False)
                    elapsed = round(time.monotonic()-started,2)
                    if response.status_code >= 400:
                        try:
                            err=response.json().get("error",{})
                            message=str(err.get("message",""))[:500] if isinstance(err,dict) else "unknown"
                            code=err.get("code") if isinstance(err,dict) else None
                        except Exception: message="non-JSON error"; code=None
                        item.update({"result":"FAIL","http_status":response.status_code,"error_code":code,"error":message,"elapsed_seconds":elapsed})
                    else:
                        result=response.json(); choices=result.get("choices") or []
                        if not choices: raise RuntimeError("No Groq choices")
                        choice=choices[0]; analysis=(choice.get("message") or {}).get("content")
                        finish=choice.get("finish_reason"); usage=result.get("usage") or {}
                        if not isinstance(analysis,str) or not analysis.strip() or finish!="stop":
                            raise RuntimeError("Incomplete/empty response: finish_reason="+str(finish))
                        status=contract.validate_analysis(analysis)
                        watch=pipeline.extract_json_block(analysis,"market_watch")
                        plan=pipeline.extract_json_block(analysis,"trade_plan")
                        if not isinstance(watch,dict) or not isinstance(watch.get("zones"),list):
                            raise RuntimeError("market_watch schema validation failed")
                        item.update({"result":"PASS","elapsed_seconds":elapsed,"model":result.get("model",MODEL),
                            "finish_reason":finish,"analysis_status":status,"market_watch_zones":len(watch["zones"]),
                            "trade_plan_present":isinstance(plan,dict),
                            "usage":{k:usage.get(k) for k in ("prompt_tokens","completion_tokens","total_tokens") if usage.get(k) is not None},
                            "analysis_excerpt":analysis[:1800]})
                except Exception as exc:
                    item.update({"result":"FAIL","elapsed_seconds":round(time.monotonic()-started,2),"error":str(exc)[:600]})
                variants[fmt]=item
                print("GROQ_WEBP_AB_PROGRESS="+json.dumps({fmt:item},ensure_ascii=False),flush=True)
            both=all(variants[f]["result"]=="PASS" for f in ("png","webp"))
            summary={"result":"PASS_BOTH_ENCODINGS" if both else "PARTIAL_OR_FAILED","model":MODEL,
                "memory_status":memory_status,"chart_candles":{x["interval"]:x.get("candles_sent") for x in charts},
                "chart_quality_flags":{x["interval"]:x.get("quality_review_required") for x in charts},
                "data_quality_gate_passed":bool(m5) and not m5.get("timestamp_stale") and not any(x.get("quality_review_required") for x in charts),
                "same_market_input_for_both":True,"variants":variants,
                "publication":"DISABLED_BY_TEST","telegram_cloudflare_orders":"NOT_EXECUTED"}
            print("GROQ_WEBP_AB_VALIDATION="+json.dumps(summary,ensure_ascii=False,sort_keys=True),flush=True)
            return 0 if both else 1
        finally: os.chdir(old)
if __name__=="__main__":
    try: sys.exit(main())
    except Exception as exc:
        import traceback
        print("RESULT=FAIL_GROQ_WEBP_AB")
        print("ERROR="+(str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__)[:700])
        traceback.print_exc(); sys.exit(1)
