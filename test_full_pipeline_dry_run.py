"""Run the production publication_guard pipeline with external publication disabled."""
import json
from pathlib import Path

import main as pipeline
import publication_guard

CAPTURE_DIR = Path("journal") / "dry_run_external_effects"
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

def dry_run_ingest(config, record, analysis, safety_gate, m5_diagnostic):
    # Build the exact production payload, but never make the Cloudflare network call.
    payload = pipeline.build_analysis_ingest_payload(
        record, analysis, safety_gate, m5_diagnostic)
    (CAPTURE_DIR / "cloudflare_ingest_payload.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "stage": "external_effect_intercepted",
        "effect": "cloudflare_analysis_ingest",
        "network_call": False,
        "payload_saved": True,
        "analysis_status": payload.get("meta", {}).get("analysis_status"),
        "safety_gate_passed": payload.get("meta", {}).get("safety_gate", {}).get("passed"),
    }, ensure_ascii=False))
    return {
        "ok": True,
        "received_at": None,
        "duplicate": False,
        "quality_status": payload.get("meta", {}).get("quality_status"),
    }

# Intercept the sole external publication write before production main() runs.
pipeline.upload_analysis_context = dry_run_ingest

print("FULL_PIPELINE_DRY_RUN_START")
print("Production entrypoint: publication_guard.main()")
print("Production hooks: zone_level_contract + quality_evidence")
print("Cloudflare ingest: intercepted; no network write")
print("Telegram: no send function is called by the production pipeline")
print("Orders: manual_only_no_auto_trading")
result = publication_guard.main()

records = sorted(Path("journal").glob("*/record.json"), key=lambda p: p.stat().st_mtime)
if not records:
    raise RuntimeError("No production journal record was created")
record_path = records[-1]
record = json.loads(record_path.read_text(encoding="utf-8"))
summary = {
    "result_code": result,
    "journal": str(record_path),
    "status": record.get("status"),
    "stage": record.get("stage"),
    "ai_provider": record.get("ai_provider"),
    "ai_model": record.get("ai_model"),
    "sensenova_finish_reason": record.get("sensenova_finish_reason"),
    "safety_gate": record.get("safety_gate"),
    "analysis_ingest": record.get("analysis_ingest"),
    "telegram": record.get("telegram"),
    "plan_upload": record.get("plan_upload"),
    "execution": record.get("execution"),
    "chart_intervals": [c.get("interval") for c in record.get("charts", [])],
    "provider_diagnostic": record.get("provider_diagnostic"),
}
(CAPTURE_DIR / "pipeline_summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print("FULL_PIPELINE_DRY_RUN_SUMMARY " + json.dumps(summary, ensure_ascii=False))
if result != 0:
    raise SystemExit(result)
print("FULL_PIPELINE_DRY_RUN_PASSED")
