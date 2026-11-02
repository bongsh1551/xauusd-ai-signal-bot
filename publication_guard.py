"""Fail closed before publishing unverified analysis to Cloudflare."""
import sys
import sensenova_runner as runner

_original_upload = runner.pipeline.upload_plan

def guarded_upload(config, analysis, record):
    gate = record.get('safety_gate')
    charts = record.get('charts')
    verified = (record.get('mode') == 'live'
                and isinstance(gate, dict)
                and gate.get('passed') is True
                and gate.get('reasons') == []
                and isinstance(charts, list)
                and len(charts) == 3
                and {c.get('interval') for c in charts if isinstance(c, dict)} == {'5min', '15min', '1h'}
                and all(isinstance(c, dict)
                        and c.get('market_session_verified') is True
                        and c.get('timestamp_stale') is False
                        and c.get('run_is_myt_weekend') is False for c in charts))
    if not verified:
        raise RuntimeError('Publication guard: test/unverified analysis retained in journal; Cloudflare upload blocked')
    return _original_upload(config, analysis, record)

if __name__ == '__main__':
    runner.pipeline.upload_plan = guarded_upload
    sys.exit(runner.main())
