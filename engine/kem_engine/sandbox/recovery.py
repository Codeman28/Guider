"""Crash recovery (SPEC §12 Phase 5): a ledger of open sandboxes so an engine that died mid-demo
(power loss, killed app) cleans up its own Office instances on the next start — and nothing else.

An orphan is closed only when ALL of these hold:
  * the PID is alive and its process creation time equals the one recorded (PIDs get reused);
  * every visible frame window of that process shows the sandbox document's caption (the user has not
    opened their own file into the instance since).
Otherwise the entry is dropped and the process left alone.
"""
from __future__ import annotations

import ctypes
import json
import os
import threading
from ctypes import wintypes
from pathlib import Path

import structlog

from ..env import win32

log = structlog.get_logger()
_lock = threading.Lock()


def ledger_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Kem"
    base.mkdir(parents=True, exist_ok=True)
    return base / "sandboxes.json"


def process_created(pid: int) -> int | None:
    """Process creation FILETIME as an int, or None if the process is gone."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        c, e, k, u = (wintypes.FILETIME() for _ in range(4))
        if not k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
            return None
        return (c.dwHighDateTime << 32) | c.dwLowDateTime
    finally:
        k32.CloseHandle(h)


def _read(path: Path) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []


def _write(path: Path, entries: list[dict]) -> None:
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")


def record(app: str, pid: int, frame_class: str, caption_prefix: str, path: Path | None = None) -> None:
    path = path or ledger_path()
    with _lock:
        entries = [e for e in _read(path) if e["pid"] != pid]
        entries.append({"app": app, "pid": pid, "created": process_created(pid), "frame_class": frame_class,
                        "caption": caption_prefix})
        _write(path, entries)


def forget(pid: int, path: Path | None = None) -> None:
    path = path or ledger_path()
    with _lock:
        _write(path, [e for e in _read(path) if e["pid"] != pid])


def is_safe_orphan(entry: dict, created=process_created, frames=None) -> bool:
    if not entry.get("created") or created(entry["pid"]) != entry["created"]:
        return False  # gone, or the PID now belongs to another process
    frames = frames if frames is not None else [
        h for h in win32.top_level_windows(entry["pid"]) if win32.class_name(h) == entry["frame_class"]]
    captions = [win32.window_text(h) if isinstance(h, int) else h for h in frames]
    return bool(captions) and all(c.startswith(entry["caption"]) for c in captions)


def recover(path: Path | None = None, kill=None) -> list[dict]:
    """Run once at engine start. Returns the entries handled, with what was done."""
    path = path or ledger_path()
    kill = kill or win32.terminate_process
    done = []
    with _lock:
        for e in _read(path):
            if is_safe_orphan(e):
                ok = kill(e["pid"])
                done.append({**e, "action": "terminated" if ok else "terminate_failed"})
                log.warning("recovery.orphan_closed", app=e["app"], pid=e["pid"], ok=ok)
            else:
                done.append({**e, "action": "left_alone"})
        _write(path, [])
    return done
