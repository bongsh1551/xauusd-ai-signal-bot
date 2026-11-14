#!/usr/bin/env python3
"""Read-only Twelve Data XAU/USD M5 history exporter."""
import argparse, csv, json, os, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import requests

BASE_URL = "https://api.twelvedata.com/time_series"
SYMBOL, INTERVAL = "XAU/USD", "5min"
CHUNK_DAYS, MIN_SECONDS_BETWEEN_CALLS, MAX_RETRIES = 7, 8.2, 3
API_CALLS_USED = 0
API_CALLS_CAP = 700

def args_parse():
    p=argparse.ArgumentParser()
    p.add_argument("--start-date",required=True)
    p.add_argument("--end-date",required=True)
    p.add_argument("--max-requests",type=int,default=700)
    p.add_argument("--out-dir",default="twelvedata_export")
    return p.parse_args()

def scrub(value):
    s=str(value or "")
    for key in (os.getenv("TWELVEDATA_API_KEY",""),os.getenv("TWELVEDATA_API_KEY_2","")):
        if key: s=s.replace(key,"[REDACTED]")
    return s[:300]

def fetch(session,key,start,end,no):
    global API_CALLS_USED
    params={"symbol":SYMBOL,"interval":INTERVAL,
      "start_date":f"{start.isoformat()} 00:00:00",
      "end_date":f"{end.isoformat()} 23:59:59",
      "timezone":"UTC","format":"JSON","apikey":key}
    for attempt in range(1,MAX_RETRIES+1):
        if API_CALLS_USED >= API_CALLS_CAP:
            raise RuntimeError("API call safety cap reached; stopping before daily quota is exhausted")
        API_CALLS_USED += 1
        try: response=session.get(BASE_URL,params=params,timeout=(15,60))
        except requests.RequestException as exc:
            if attempt==MAX_RETRIES: raise RuntimeError(f"request {no}: network error ({type(exc).__name__})") from None
            time.sleep(10*attempt); continue
        if response.status_code==429:
            if attempt==MAX_RETRIES: raise RuntimeError(f"request {no}: HTTP 429 after retries")
            time.sleep(65); continue
        if response.status_code!=200: raise RuntimeError(f"request {no}: HTTP {response.status_code}")
        try: data=response.json()
        except ValueError: raise RuntimeError(f"request {no}: invalid JSON") from None
        if data.get("status")=="error" or "values" not in data:
            raise RuntimeError(f"request {no}: provider error {data.get('code','UNKNOWN')}: {scrub(data.get('message'))}")
        meta=data.get("meta",{})
        if meta.get("symbol")!=SYMBOL or meta.get("interval")!=INTERVAL:
            raise RuntimeError(f"request {no}: unexpected symbol/interval metadata")
        return data.get("values") or [],meta
    raise RuntimeError(f"request {no}: retries exhausted")

def main():
    a=args_parse(); start=date.fromisoformat(a.start_date); end=date.fromisoformat(a.end_date)
    if end<start: raise SystemExit("end-date must be on/after start-date")
    if not 1<=a.max_requests<=750: raise SystemExit("max-requests must be 1..750")
    chunks=[]; cur=start
    while cur<=end:
        last=min(cur+timedelta(days=CHUNK_DAYS-1),end); chunks.append((cur,last)); cur=last+timedelta(days=1)
    if len(chunks)>a.max_requests: raise SystemExit(f"Range requires {len(chunks)} calls; cap is {a.max_requests}.")
    global API_CALLS_CAP
    API_CALLS_CAP=a.max_requests
    key=os.getenv("TWELVEDATA_API_KEY","").strip() or os.getenv("TWELVEDATA_API_KEY_2","").strip()
    if not key: raise SystemExit("Missing TWELVEDATA_API_KEY and TWELVEDATA_API_KEY_2 repository secrets")
    out=Path(a.out_dir); out.mkdir(parents=True,exist_ok=True)
    rows={}; log=[]; session=requests.Session()
    session.headers.update({"User-Agent":"GApps-Signal-Research-History-Exporter/1.0"})
    started=datetime.now(timezone.utc); previous=None
    for i,(lo,hi) in enumerate(chunks,1):
        if previous is not None:
            wait=MIN_SECONDS_BETWEEN_CALLS-(time.monotonic()-previous)
            if wait>0: time.sleep(wait)
        values,meta=fetch(session,key,lo,hi,i); previous=time.monotonic(); accepted=0
        for item in values:
            try:
                dt=datetime.strptime(item["datetime"],"%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                o,h,l,c=[float(item[k]) for k in ("open","high","low","close")]
                if min(o,h,l,c)<=0 or h<max(o,c,l) or l>min(o,c,h): continue
            except (ValueError,TypeError,KeyError): continue
            stamp=dt.isoformat().replace("+00:00","Z"); rows[stamp]=(stamp,o,h,l,c); accepted+=1
        log.append({"request_no":i,"start":lo.isoformat(),"end":hi.isoformat(),
                    "rows_received":len(values),"rows_accepted":accepted,
                    "symbol":meta.get("symbol"),"interval":meta.get("interval")})
        print(f"[{i}/{len(chunks)}] {lo} to {hi}: {accepted} candles",flush=True)
    if not rows: raise SystemExit("No valid candles returned; verify XAU/USD history entitlement.")
    ordered=[rows[k] for k in sorted(rows)]
    csvpath=out/"XAUUSD_TwelveData_M5_UTC.csv"
    with csvpath.open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["timestamp_utc","open","high","low","close"]); w.writerows(ordered)
    meta={"provider":"Twelve Data","symbol":SYMBOL,"interval":INTERVAL,"timezone":"UTC",
      "start_date_requested":start.isoformat(),"end_date_requested_inclusive":end.isoformat(),
      "first_candle_utc":ordered[0][0],"last_candle_utc":ordered[-1][0],"candles":len(ordered),
      "duplicate_timestamps_overwritten":sum(x["rows_accepted"] for x in log)-len(ordered),
      "requests_used":len(log),"api_calls_attempted":API_CALLS_USED,"chunk_days":CHUNK_DAYS,"started_utc":started.isoformat(),
      "finished_utc":datetime.now(timezone.utc).isoformat(),"request_log":log,
      "note":"Research export only. Validate price alignment against GApps feed before creating labels."}
    (out/"metadata.json").write_text(json.dumps(meta,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in meta.items() if k!="request_log"},indent=2))
    print(f"Saved: {csvpath}")

if __name__=="__main__": main()
