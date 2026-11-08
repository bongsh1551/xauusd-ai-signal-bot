import json
import os
import time

import run_replay


def test_update_replay_writes_and_refreshes(tmp_path):
    replay_dir = tmp_path / 'replay'
    record = {
        'run_id': 'run-1', 'code_commit': 'abc', 'mode': 'shadow',
        'ai_model': 'test-model', 'stage': 'gemini', 'status': 'running',
        'charts': [{'interval': '5min'}], 'market_memory': {'status': 'SAVED'},
        'prompt_sha256': 'hash', 'ai_raw_output': 'raw',
        'trade_plan': {'status': 'WAIT'}, 'market_watch': {'zones': []},
        'evidence_package': {'zones': [{'scenario_id': 'SELL:M15:x'}]},
        'provider_diagnostic': {'zone_lifecycle': {'zones': []}, 'analysis_status': 'WAIT'},
        'safety_gate': {'passed': True, 'reasons': []},
        'analysis_ingest': {'attempted': False}, 'telegram': {'attempted': False},
        'plan_upload': {'attempted': False},
    }
    path = run_replay.update_replay(record, tmp_path, replay_dir=replay_dir)
    assert path.name == 'run-1.json'
    first = json.loads(path.read_text(encoding='utf-8'))
    assert first['run_id'] == 'run-1'
    assert first['market_data']['charts'][0]['interval'] == '5min'
    assert first['evidence_package']['zones'][0]['scenario_id'] == 'SELL:M15:x'
    assert first['lifecycle_result'] == {'zones': []}
    assert first['validator_result']['analysis_status'] == 'WAIT'

    record['status'] = 'completed'
    record['stage'] = 'completed'
    run_replay.update_replay(record, tmp_path, replay_dir=replay_dir)
    second = json.loads(path.read_text(encoding='utf-8'))
    assert second['status'] == 'completed'
    assert second['stage'] == 'completed'


def test_update_replay_prunes_old_files(tmp_path):
    replay_dir = tmp_path / 'replay'
    old = replay_dir / 'old.json'
    replay_dir.mkdir(parents=True)
    old.write_text('{}', encoding='utf-8')
    old_time = time.time() - (run_replay.RETENTION_SECONDS + 60)
    os.utime(old, (old_time, old_time))

    record = {'run_id': 'run-2'}
    run_replay.update_replay(record, tmp_path, replay_dir=replay_dir)
    assert not old.exists()
    assert (replay_dir / 'run-2.json').exists()


def test_update_replay_ignores_invalid_record(tmp_path):
    replay_dir = tmp_path / 'replay'
    assert run_replay.update_replay({}, tmp_path, replay_dir=replay_dir) is None
    assert run_replay.update_replay(None, tmp_path, replay_dir=replay_dir) is None
    assert not replay_dir.exists()
