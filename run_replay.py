"""Run replay log: retain an auditable, per-run analysis and validation record."""
import json
import time
from pathlib import Path

REPLAY_DIR = Path('.cache/run_replay')
RETENTION_SECONDS = 48 * 60 * 60


def build_replay(record):
    """Build a replay payload from the existing run record; never include secrets."""
    diagnostic = record.get('provider_diagnostic') or {}
    return {
        'run_id': record.get('run_id'),
        'code_commit': record.get('code_commit'),
        'created_at_utc': record.get('created_at_utc'),
        'created_at_myt': record.get('created_at_myt'),
        'mode': record.get('mode'),
        'ai_model': record.get('ai_model'),
        'stage': record.get('stage'),
        'status': record.get('status'),
        'market_data': {
            'charts': record.get('charts', []),
            'current_price': record.get('current_price'),
        },
        'daily_memory': record.get('market_memory'),
        'prompt_sha256': record.get('prompt_sha256'),
        'ai_raw_output': record.get('ai_raw_output'),
        'parsed_plan': record.get('trade_plan'),
        'market_watch': record.get('market_watch'),
        'lifecycle_result': diagnostic.get('zone_lifecycle'),
        'validator_result': {
            'analysis_status': diagnostic.get('analysis_status'),
            'safety_gate': record.get('safety_gate'),
        },
        'analysis_ingest': record.get('analysis_ingest'),
        'telegram': record.get('telegram'),
        'plan_upload': record.get('plan_upload'),
        'error': record.get('error'),
        'updated_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }


def update_replay(record, folder, replay_dir=None):
    """Write or refresh the replay file for one run; failures must not break analysis."""
    run_id = record.get('run_id') if isinstance(record, dict) else None
    if not run_id:
        return None
    base = Path(replay_dir) if replay_dir else REPLAY_DIR
    base.mkdir(parents=True, exist_ok=True)
    path = base / (str(run_id) + '.json')
    payload = build_replay(record)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)
    _prune(base)
    return path


def _prune(base, now=None):
    cutoff = (now if now is not None else time.time()) - RETENTION_SECONDS
    for path in base.glob('*.json'):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass
