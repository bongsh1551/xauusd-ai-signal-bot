"""Run the production publication_guard pipeline with external publication disabled."""
import json
from datetime import datetime, timezone
from pathlib import Path

import publication_guard

runner = publication_guard.runner
pipeline = runner.pipeline
upload_calls = []

def dry_run_ingest(config, record, analysis, safety_gate, m5_diagnostic):
    # Construct the exact production ingest payload; never make a Cloudflare request.
    payload = pipeline.build_analysis_ingest_payload(record, analysis, safety_gate, m5_diagnostic)
    meta = payload.get("meta", {})
    summary = {
        "dry_run": True,
        "network_request_made": False,
        "run_id": record.get("run_id"),
        "analysis_status": meta.get("analysis_status"),
        "analysis_complete": meta.get("analysis_complete"),
        "analysis_usable": meta.get("analysis_usable"),
        "quality_status": meta.get("quality_status"),
        "quality_reasons": meta.get("quality_reasons"),
        "publish_allowed": meta.get("publish_allowed"),
        "safety_gate": meta.get("safety_gate"),
        "data_as_of_utc": meta.get("data_as_of_utc"),
        "chart_intervals": [c.get("interval") for c in meta.get("charts", [])],
        "quality_evidence_versions": [
            (c.get("quality_evidence") or {}).get("version") for c in meta.get("charts", [])
        ],
        "trade_plan_status": (meta.get("trade_plan") or {}).get("status"),
        "market_watch_zone_count": len((meta.get("market_watch") or {}).get("zones", [])),
        "evidence_zone_count": len((meta.get("evidence_package") or {}).get("zones", [])),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    folder = Path("journal") / str(record["run_id"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "dry_run_cloudflare_ingest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    upload_calls.append(summary)
    print("CLOUDFLARE_DRY_RUN_INTERCEPTED " + json.dumps(summary, ensure_ascii=False), flush=True)
    return {
        "ok": True,
        "received_at": summary["captured_at_utc"],
        "duplicate": False,
        "quality_status": meta.get("quality_status"),
        "dry_run": True,
    }

# Twelve Data and SenseNova remain live. Only the Cloudflare publication write is stubbed.
pipeline.upload_analysis_context = dry_run_ingest

outcome = "COMPLETED"
try:
    result_code = publication_guard.main()
    if result_code != 0:
        raise RuntimeError("Production pipeline returned exit code " + str(result_code))
except publication_guard.SafetyBlocked as exc:
    outcome = "SAFETY_BLOCKED"
    print("EXPECTED_SAFETY_BLOCK " + str(exc), flush=True)

if len(upload_calls) != 1:
    raise RuntimeError("Expected one intercepted Cloudflare payload; got " + str(len(upload_calls)))

summary = upload_calls[0]
record_path = Path("journal") / str(summary["run_id"]) / "record.json"
if not record_path.exists():
    raise RuntimeError("Production journal record was not created: " + str(record_path))
record = json.loads(record_path.read_text(encoding="utf-8"))

# The pipeline sees a successful local stub to continue its normal journal path.
# Correct the persisted audit record so a dry-run can never masquerade as a real upload.
record["analysis_ingest"] = {
    "attempted": False,
    "sent": False,
    "dry_run": True,
    "network_request_made": False,
    "payload_built": True,
    "note": "Payload validated locally; Cloudflare endpoint was not called.",
}
record["dry_run"] = True
record["publication_side_effects"] = {
    "cloudflare_ingest": False,
    "telegram": False,
    "plan_upload": False,
    "automatic_orders": False,
}
record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
# Keep replay artifact consistent with the corrected journal.
import run_replay
run_replay.update_replay(record, record_path.parent)

if record.get("analysis_ingest", {}).get("sent") is not False:
    raise RuntimeError("Dry-run must never be recorded as a successful real upload")
if record.get("analysis_ingest", {}).get("dry_run") is not True:
    raise RuntimeError("Dry-run audit marker missing")
if record.get("telegram", {}).get("sent") is not False:
    raise RuntimeError("Unexpected Telegram send marker")
if record.get("execution") != "manual_only_no_auto_trading":
    raise RuntimeError("Unexpected execution mode")

if outcome == "SAFETY_BLOCKED":
    if record.get("status") != "blocked" or record.get("stage") != "safety_blocked":
        raise RuntimeError("Safety block was raised but not persisted")
    if record.get("publication_decision") != "BLOCKED_UNVERIFIED":
        raise RuntimeError("Safety block decision was not persisted")
else:
    if record.get("status") != "completed":
        raise RuntimeError("Pipeline returned success but journal is not completed")
    if not (record.get("safety_gate") or {}).get("passed"):
        raise RuntimeError("Pipeline completed despite a failed safety gate")

result = {
    "event": "PRODUCTION_PIPELINE_DRY_RUN_PASSED",
    "outcome": outcome,
    "run_id": record.get("run_id"),
    "stage": record.get("stage"),
    "status": record.get("status"),
    "ai_provider": record.get("ai_provider"),
    "ai_model": record.get("ai_model"),
    "sensenova_finish_reason": record.get("sensenova_finish_reason"),
    "analysis_status": summary.get("analysis_status"),
    "safety_gate": summary.get("safety_gate"),
    "quality_status": summary.get("quality_status"),
    "chart_intervals": summary.get("chart_intervals"),
    "quality_evidence_versions": summary.get("quality_evidence_versions"),
    "cloudflare_network_request": False,
    "telegram_sent": False,
    "automatic_orders": False,
    "journal_path": str(record_path.parent),
}
print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
