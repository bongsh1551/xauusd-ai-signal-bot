"""Fail closed before Telegram and Cloudflare; journal expected safety blocks."""
import sys
import sensenova_runner as runner
from sensenova_transport import install
from zone_level_contract import install_zone_levels

_original_upload = runner.pipeline.upload_plan
_original_save = runner.save_record
_BLOCK_MESSAGE = 'Safety block: unverified analysis retained in journal; publication skipped'
_block_pending = False
_block_saved = False

class SafetyBlocked(RuntimeError):
    pass

def verified_record(record):
    gate = record.get('safety_gate')
    charts = record.get('charts')
    return (record.get('mode') == 'live'
            and isinstance(gate, dict)
            and gate.get('passed') is True
            and gate.get('reasons') == []
            and isinstance(charts, list)
            and len(charts) == 3
            and {c.get('interval') for c in charts if isinstance(c, dict)} == {'5min', '15min', '1h'}
            and all(isinstance(c, dict)
                    and c.get('market_session_verified') is True
                    and c.get('timestamp_stale') is False
                    and c.get('run_is_myt_weekend') is False
                    and c.get('quality_review_required') is False
                    and c.get('quality_verdict') == 'NO_NARROW_RUN_FLAG'
                    for c in charts))

def guarded_upload(config, analysis, record):
    if not verified_record(record):
        raise RuntimeError('Publication guard: test/unverified analysis retained in journal; Cloudflare upload blocked')
    return _original_upload(config, analysis, record)

def shadow_telegram_allowed(record):
    """Shadow mode may publish WAIT-only observations, never actionable plans."""
    gate = record.get('safety_gate')
    plan = record.get('trade_plan')
    return (record.get('mode') == 'shadow'
            and isinstance(gate, dict) and gate.get('passed') is False
            and bool(gate.get('reasons'))
            and not (isinstance(plan, dict) and plan.get('status') == 'ENTRY_READY'))

def guarded_save(path, record):
    global _block_pending, _block_saved
    if (record.get('stage') == 'telegram'
            and record.get('status') == 'running'
            and not verified_record(record)):
        if shadow_telegram_allowed(record):
            return _original_save(path, record)
        record['telegram'] = {'attempted': False, 'sent': False}
        record['plan_upload'] = {'attempted': False, 'sent': False}
        record['publication_decision'] = 'BLOCKED_UNVERIFIED'
        _original_save(path, record)
        _block_pending = True
        raise SafetyBlocked(_BLOCK_MESSAGE)
    if (_block_pending and record.get('stage') == 'telegram'
            and record.get('status') == 'failed'
            and record.get('error') == _BLOCK_MESSAGE):
        record['status'] = 'blocked'
        record['stage'] = 'safety_blocked'
        record['blocked_reason'] = _BLOCK_MESSAGE
        _original_save(path, record)
        _block_pending = False
        _block_saved = True
        return
    return _original_save(path, record)

def main():
    global _block_pending, _block_saved
    _block_pending = False
    _block_saved = False
    runner.pipeline.upload_plan = guarded_upload
    runner.save_record = guarded_save
    install(runner)
    install_zone_levels(runner)
    result = runner.main()
    if result == 1 and _block_saved and not _block_pending:
        print('Safety block journaled; no Telegram or Cloudflare publication; live readiness NOT verified')
        return 0
    return result

if __name__ == '__main__':
    sys.exit(main())
