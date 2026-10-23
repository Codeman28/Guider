from kem_engine.sandbox import recovery


def test_ledger_record_forget_and_recover(tmp_path, monkeypatch):
    p = tmp_path / "s.json"
    monkeypatch.setattr(recovery, "process_created", lambda pid: 111 if pid in (1, 2, 3) else None)
    recovery.record("Excel", 1, "XLMAIN", "Book1", p)
    recovery.record("Word", 2, "OpusApp", "Document1", p)
    recovery.record("Excel", 3, "XLMAIN", "Book2", p)
    recovery.forget(3, p)
    killed = []
    monkeypatch.setattr(recovery, "is_safe_orphan", lambda e: e["pid"] == 1)
    done = recovery.recover(p, kill=lambda pid: killed.append(pid) or True)
    assert killed == [1]
    assert {d["pid"]: d["action"] for d in done} == {1: "terminated", 2: "left_alone"}
    assert recovery._read(p) == []


def test_is_safe_orphan_rules():
    e = {"pid": 7, "created": 42, "frame_class": "XLMAIN", "caption": "Book1"}
    same = lambda pid: 42
    assert recovery.is_safe_orphan(e, created=same, frames=["Book1 - Excel"])
    assert not recovery.is_safe_orphan(e, created=lambda pid: 43, frames=["Book1 - Excel"])  # PID reused
    assert not recovery.is_safe_orphan(e, created=lambda pid: None, frames=["Book1 - Excel"])  # gone
    assert not recovery.is_safe_orphan(e, created=same, frames=["Book1 - Excel", "Doanh thu.xlsx - Excel"])
    assert not recovery.is_safe_orphan(e, created=same, frames=[])
    assert not recovery.is_safe_orphan({**e, "created": None}, created=same, frames=["Book1"])


def test_process_created_for_self_and_missing():
    import os
    assert recovery.process_created(os.getpid())
    assert recovery.process_created(0x7FFFFFF0) is None
