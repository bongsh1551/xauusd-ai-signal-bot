import publication_guard


def _chart(interval):
    return {
        "interval": interval,
        "timestamp_stale": False,
        "run_is_myt_weekend": False,
        "quality_review_required": False,
        "quality_verdict": "NO_NARROW_RUN_FLAG",
    }


def _record(**overrides):
    value = {
        "mode": "manual_signals",
        "stage": "telegram",
        "status": "running",
        "safety_gate": {"passed": True, "reasons": []},
        "charts": [_chart("5min"), _chart("15min"), _chart("1h")],
        "telegram": {"attempted": True, "sent": False},
        "plan_upload": {"attempted": True, "sent": False},
    }
    value.update(overrides)
    return value


def test_unverified_running_record_is_blocked_before_publication(tmp_path, monkeypatch):
    saved = []
    monkeypatch.setattr(publication_guard, "_original_save", lambda path, record: saved.append(dict(record)))
    monkeypatch.setattr(publication_guard, "_block_pending", False)
    monkeypatch.setattr(publication_guard, "_block_saved", False)
    record = _record(safety_gate={"passed": False, "reasons": ["M5_STALE"]})

    try:
        publication_guard.guarded_save(tmp_path / "record.json", record)
        assert False, "SafetyBlocked should be raised"
    except publication_guard.SafetyBlocked:
        pass

    assert len(saved) == 1
    assert saved[0]["publication_decision"] == "BLOCKED_UNVERIFIED"
    assert saved[0]["telegram"] == {"attempted": False, "sent": False}
    assert saved[0]["plan_upload"] == {"attempted": False, "sent": False}
    assert publication_guard._block_pending is True


def test_safety_block_failure_record_is_journaled_as_blocked(tmp_path, monkeypatch):
    saved = []
    monkeypatch.setattr(publication_guard, "_original_save", lambda path, record: saved.append(dict(record)))
    monkeypatch.setattr(publication_guard, "_block_pending", True)
    monkeypatch.setattr(publication_guard, "_block_saved", False)
    record = _record(status="failed", error=publication_guard._BLOCK_MESSAGE)

    publication_guard.guarded_save(tmp_path / "record.json", record)

    assert saved[-1]["status"] == "blocked"
    assert saved[-1]["stage"] == "safety_blocked"
    assert saved[-1]["blocked_reason"] == publication_guard._BLOCK_MESSAGE
    assert publication_guard._block_pending is False
    assert publication_guard._block_saved is True


def test_verified_record_can_pass_guard_without_external_side_effects(tmp_path, monkeypatch):
    saved = []
    monkeypatch.setattr(publication_guard, "_original_save", lambda path, record: saved.append(dict(record)))
    monkeypatch.setattr(publication_guard, "_block_pending", False)
    monkeypatch.setattr(publication_guard, "_block_saved", False)
    record = _record()

    publication_guard.guarded_save(tmp_path / "record.json", record)

    assert saved == [record]
    assert publication_guard._block_pending is False
