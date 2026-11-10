import base64, json, os, time, hashlib, tempfile
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from pathlib import Path
import pandas as pd, requests, matplotlib
matplotlib.use("Agg")
import main as pipeline, daily_memory
from fundamentals import collect_fundamentals
from sensenova_runner import MODEL, ENDPOINT

def err(r):
    try: body=json.dumps(r.json().get("error",r.json()),ensure_ascii=False)
    except Exception: body=r.text
    key=os.getenv("SENSENOVA_API_KEY","")
    return (body.replace(key,"[REDACTED]") if key else body)[:1800]

def install_twelvedata_diagnostics(td_key):
    original = pipeline.api_json

    def diagnostic_api_json(response, service, secrets):
        if response.status_code != 200:
            raw_url = response.request.url if response.request else ""
            if raw_url:
                parts = urlsplit(raw_url)
                query = [(k, "[REDACTED]" if k.lower() in {"apikey", "api_key", "token", "key"} else v)
                         for k, v in parse_qsl(parts.query, keep_blank_values=True)]
                safe_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
            else:
                safe_url = None
            body = response.text or ""
            for secret in secrets:
                if secret:
                    body = body.replace(secret, "[REDACTED]")
            try:
                parsed = response.json()
                provider_message = parsed.get("message") or parsed.get("error", {}).get("message")
                provider_code = parsed.get("code")
                provider_status = parsed.get("status")
            except Exception:
                provider_message = provider_code = provider_status = None
            safe_headers = {k: response.headers.get(k) for k in
                            ("content-type", "date", "server", "x-request-id", "request-id")
                            if response.headers.get(k)}
            print(json.dumps({
                "stage": "twelvedata_raw_http_error",
                "service": service,
                "http_status": response.status_code,
                "request_url_redacted": safe_url,
                "provider_code": provider_code,
                "provider_status": provider_status,
                "provider_message": provider_message,
                "response_body_redacted": body[:3000],
                "safe_response_headers": safe_headers,
                "api_key_present": bool(td_key),
                "api_key_length": len(td_key),
                "api_key_sha256_prefix": hashlib.sha256(td_key.encode()).hexdigest()[:12]
            }, ensure_ascii=False), flush=True)
        return original(response, service, secrets)

    pipeline.api_json = diagnostic_api_json


def main():
    td=os.environ["TWELVEDATA_API_KEY"].strip()
    key=os.environ["SENSENOVA_API_KEY"].strip()
    install_twelvedata_diagnostics(td)
    now=pd.Timestamp.now(tz="UTC"); local=now.tz_convert("Asia/Kuala_Lumpur")
    pipeline.ANALYSIS_MODE="manual_signals"
    pipeline.HEADER="🟡 XAUUSD 手动信号分析｜不自动下单"
    folder=Path(tempfile.mkdtemp(prefix="sensenova-full-load-"))
    state,mstatus=daily_memory.load_state(pipeline.MEMORY_PATH,now.to_pydatetime(),"manual_signals")
    prompt=Path(pipeline.PROMPT_PATH).read_text(encoding="utf-8").strip()
    instruction=(prompt+"\n\n【执行模式】实时手动信号模式：每轮分析最新已收线行情，按证据输出 WAIT、APPROACH 或 CONFIRMED；满足条件时发布 ENTRY_READY 参考计划。只提供人工决策参考，绝不自动下单。\n"+pipeline.HEADER+"\n当前 UTC："+now.isoformat()+"\n当前大马时间："+local.isoformat()+"\n不编造宏观背景，不把新时间戳等同于有效行情。只基于以下输入。")
    memory=daily_memory.context_text(state,now.to_pydatetime())
    if state.get("opening_plan") is None: memory+="\nNo opening plan exists for the current MYT date. Establish a fresh opening context today; prior_session_context is reference only."
    parts=[{"text":instruction},{"text":"【DAILY MARKET MEMORY｜24小时连续上下文】\n"+memory}]
    charts=[]
    for interval,mins in [("5min",5),("15min",15),("1h",60)]:
        frame,img,diag=pipeline.fetch_chart(td,interval,mins,now,folder); charts.append(diag)
        txt=interval+" 已收线 OHLC，UTC：\n"+frame.tail(40).to_csv(index_label="timestamp_utc")+"\n程序诊断："+json.dumps(diag,ensure_ascii=False)
        parts.extend([{"text":txt},{"inline_data":{"mime_type":"image/png","data":base64.b64encode(img).decode("ascii")}}])
    fundamentals=collect_fundamentals(td,now,folder); parts.append({"text":fundamentals["context"]})
    content=[]
    for p in parts:
        if "text" in p: content.append({"type":"text","text":p["text"]})
        else:
            im=p["inline_data"]; content.append({"type":"image_url","image_url":{"url":"data:"+im["mime_type"]+";base64,"+im["data"]}})
    payload={"model":MODEL,"messages":[{"role":"user","content":content}],"temperature":0.2,"reasoning_effort":"low","max_tokens":8192,"stream":False}
    raw=json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode()
    imgs=sum(len(p["image_url"]["url"].partition(",")[2]) for p in content if p.get("type")=="image_url")
    chars=sum(len(p.get("text","")) for p in content if p.get("type")=="text")
    print(json.dumps({"stage":"payload_ready","endpoint":ENDPOINT,"model":MODEL,"memory_status":mstatus,"prompt_sha256":hashlib.sha256(prompt.encode()).hexdigest(),"text_chars":chars,"request_json_bytes":len(raw),"image_count":3,"image_base64_chars":imgs,"chart_diagnostics":charts,"fundamental_event_count":len(fundamentals["calendar_events"]),"currency_strength":fundamentals["currency_strength"].get("status")},ensure_ascii=False),flush=True)
    s=requests.Session(); start=time.monotonic(); retry={408,429,500,502,503,504}; r=None
    for n in range(1,4):
        try:
            r=s.post(ENDPOINT,headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},json=payload,timeout=(10,120),allow_redirects=False)
            if 200<=r.status_code<300: break
            print(json.dumps({"stage":"provider_http_error","attempt":n,"http_status":r.status_code,"provider_error":err(r),"elapsed_ms":round((time.monotonic()-start)*1000,1)},ensure_ascii=False),flush=True)
            if r.status_code not in retry or n==3: raise RuntimeError("SenseNova HTTP "+str(r.status_code))
            r.close()
        except (requests.exceptions.Timeout,requests.exceptions.ConnectionError) as ex:
            print(json.dumps({"stage":"transport_error","attempt":n,"error_type":type(ex).__name__}),flush=True)
            if n==3: raise
        if n<3: time.sleep(5)
    data=r.json(); choices=data.get("choices",[])
    if not choices: raise RuntimeError("HTTP 2xx but no choices")
    c=choices[0]; msg=c.get("message",{})
    print(json.dumps({"stage":"full_payload_success","http_status":r.status_code,"elapsed_seconds":round(time.monotonic()-start,2),"finish_reason":c.get("finish_reason"),"usage":data.get("usage",{}),"response_content_chars":len(msg.get("content") or ""),"request_id":r.headers.get("x-request-id") or r.headers.get("request-id"),"telegram_sent":False,"cloudflare_ingest":False,"orders_placed":False},ensure_ascii=False),flush=True)
    if c.get("finish_reason")!="stop" or not msg.get("content"): raise RuntimeError("Incomplete or empty model output")
    print("FULL_PAYLOAD_TEST_PASSED",flush=True)

if __name__=="__main__": main()
