#!/usr/bin/env python3
"""Read-only Twelve Data XAU/USD M5 lookback probe for the Basic/free trial symbol."""
import argparse, csv, json, os
from datetime import datetime, timezone
from pathlib import Path
import requests

BASE = "https://api.twelvedata.com"
SYMBOL, INTERVAL = "XAU/USD", "5min"

def args_parse():
    p=argparse.ArgumentParser()
    p.add_argument("--outputsize",type=int,choices=(300,500),default=500)
    p.add_argument("--start-date",default="")
    p.add_argument("--end-date",default="")
    p.add_argument("--out-dir",default="twelvedata_export")
    return p.parse_args()

def scrub(value):
    s=str(value or "")
    for key in (os.getenv("TWELVEDATA_API_KEY",""),os.getenv("TWELVEDATA_API_KEY_2","")):
        if key: s=s.replace(key,"[REDACTED]")
    return s[:300]

def request_json(session, endpoint, params, key, call_no):
    safe_params=dict(params)
    safe_params["apikey"]=key
    response=session.get(f"{BASE}/{endpoint}",params=safe_params,timeout=(15,60))
    try:
        data=response.json()
    except ValueError:
        data={}
    if response.status_code!=200 or data.get("status")=="error":
        message=data.get("message","") or data.get("error","")
        code=data.get("code","unknown")
        used=response.headers.get("api-credits-used","unknown")
        left=response.headers.get("api-credits-left","unknown")
        raise RuntimeError(f"call {call_no} {endpoint}: HTTP {response.status_code}; provider_code={code}; message={scrub(message)}; credits_used={used}; credits_left={left}")
    return data, response.headers

def main():
    a=args_parse()
    key=os.getenv("TWELVEDATA_API_KEY","").strip() or os.getenv("TWELVEDATA_API_KEY_2","").strip()
    if not key: raise SystemExit("Missing TWELVEDATA_API_KEY and TWELVEDATA_API_KEY_2 repository secrets")
    out=Path(a.out_dir); out.mkdir(parents=True,exist_ok=True)
    session=requests.Session()
    session.headers.update({"User-Agent":"GApps-Signal-XAUUSD-M5-Lookback-Probe/1.0"})
    started=datetime.now(timezone.utc)

    earliest, h1=request_json(session,"earliest_timestamp",{"symbol":SYMBOL,"interval":INTERVAL},key,1)
    if bool(a.start_date) != bool(a.end_date):
        raise SystemExit("Provide both --start-date and --end-date, or neither.")
    series_params={"symbol":SYMBOL,"interval":INTERVAL,"outputsize":a.outputsize,
        "timezone":"UTC","order":"asc","format":"JSON"}
    if a.start_date:
        datetime.strptime(a.start_date,"%Y-%m-%d")
        datetime.strptime(a.end_date,"%Y-%m-%d")
        if a.end_date < a.start_date:
            raise SystemExit("end-date must be on/after start-date")
        series_params["start_date"]=f"{a.start_date} 00:00:00"
        series_params["end_date"]=f"{a.end_date} 23:59:59"
    series, h2=request_json(session,"time_series",series_params,key,2)
    meta=series.get("meta",{})
    if meta.get("symbol")!=SYMBOL or meta.get("interval")!=INTERVAL:
        raise SystemExit("Provider returned unexpected symbol or interval metadata")
    values=series.get("values") or []
    rows=[]
    for item in values:
        try:
            dt=datetime.strptime(item["datetime"],"%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            o,h,l,c=[float(item[k]) for k in ("open","high","low","close")]
            if min(o,h,l,c)<=0 or h<max(o,c,l) or l>min(o,c,h): continue
        except (ValueError,TypeError,KeyError):
            continue
        rows.append((dt.isoformat().replace("+00:00","Z"),o,h,l,c))
    rows.sort(key=lambda x:x[0])
    if not rows: raise SystemExit("No valid M5 candles returned for this Basic-plan key.")
    csvpath=out/f"XAUUSD_TwelveData_M5_last_{a.outputsize}_UTC.csv"
    with csvpath.open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["timestamp_utc","open","high","low","close"]); w.writerows(rows)

    earliest_value=earliest.get("datetime") or earliest.get("earliest_timestamp") or earliest.get("date") or earliest
    report={
      "provider":"Twelve Data","plan_context":"Basic/free key; XAU/USD trial symbol",
      "symbol":SYMBOL,"interval":INTERVAL,"timezone":"UTC",
      "earliest_timestamp_response":earliest_value,
      "requested_outputsize":a.outputsize,"requested_start_date":a.start_date or "latest",
      "requested_end_date":a.end_date or "latest","candles_returned":len(rows),
      "first_returned_candle_utc":rows[0][0],"last_returned_candle_utc":rows[-1][0],
      "lookback_hours_inclusive":round((datetime.fromisoformat(rows[-1][0].replace("Z","+00:00"))-datetime.fromisoformat(rows[0][0].replace("Z","+00:00"))).total_seconds()/3600,2),
      "api_calls":2,"credits_used_header_call1":h1.get("api-credits-used","unknown"),
      "credits_left_header_call1":h1.get("api-credits-left","unknown"),
      "credits_used_header_call2":h2.get("api-credits-used","unknown"),
      "credits_left_header_call2":h2.get("api-credits-left","unknown"),
      "started_utc":started.isoformat(),"finished_utc":datetime.now(timezone.utc).isoformat(),
      "csv_file":csvpath.name,
      "note":"This tests the Basic/free key's actual XAU/USD M5 history entitlement. Earliest timestamp endpoint and returned outputsize are reported separately."
    }
    (out/"XAUUSD_TwelveData_M5_lookback_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))
    print(f"Saved: {csvpath}")

if __name__=="__main__": main()
