"""Office sandbox core (SPEC §6.3): a private, never-saved document in Excel, Word or PowerPoint.

Each app is an AppSpec: how to add the blank document, find its window, fill a fixture, select a
reference, close without saving. The lifecycle (setup / unstick / teardown) is shared and keeps the
guarantees proven in Phase 0–2: COM retry while Office is busy, Esc before closing, quit only our own
instance, release every COM reference so the process exits.
"""
from __future__ import annotations

import gc
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import structlog

from ..env import win32
from .com import com_retry

log = structlog.get_logger()

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


class SandboxRefused(Exception):
    """Guider will not open a sandbox here (e.g. PowerPoint already running with the user's files)."""


@dataclass
class AppSpec:
    name: str
    progid: str
    frame_class: str
    dialog_classes: tuple[str, ...]
    edit_child_class: str  # child window that receives Esc to leave edit mode
    single_instance: bool
    add_doc: Callable[[Any], Any]
    doc_hwnd: Callable[[Any, Any], int]
    fill: Callable[[Any, dict], None]
    select: Callable[[Any, str], None]
    close_doc: Callable[[Any], None]
    doc_count: Callable[[Any], int]
    ping: Callable[[Any], Any]  # cheap COM call that fails "busy" while Office is in an edit/modal state


@dataclass
class SandboxHandle:
    app: object
    doc: object
    hwnd: int
    pid: int
    created_instance: bool
    spec: AppSpec | None = None
    created_at: float = field(default_factory=time.time)
    closed: bool = False


def load_fixture(fixture_id: str) -> dict:
    path = FIXTURES / f"{fixture_id}.json"
    if path.parent != FIXTURES or not path.exists():  # fixture IDs only, never arbitrary paths
        raise ValueError(f"unknown fixture {fixture_id!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def _frame_pids(spec: AppSpec) -> set[int]:
    return {win32.window_pid(h) for h in win32.top_level_windows() if win32.class_name(h) == spec.frame_class}


def setup(spec: AppSpec, fixture_id: str | None, size_logical=(1280, 800), pos=(40, 40),
          timeout: float = 60.0) -> SandboxHandle:
    from ..env import runtime
    runtime.init()  # COM apartment must be set by the UIA stack first
    import win32com.client

    before = _frame_pids(spec)
    if spec.single_instance and before:
        # S2: a second DispatchEx joins the running instance, so the sandbox would share a process with
        # the user's own documents. Refuse instead of risking them (SPEC §8).
        raise SandboxRefused(f"Hãy đóng {spec.name} rồi hỏi lại: Guider không làm mẫu khi {spec.name} "
                             "đang mở file của bạn.")
    t0 = time.monotonic()
    app = win32com.client.DispatchEx(spec.progid)
    try:
        com_retry(lambda: setattr(app, "Visible", True), timeout=timeout)
        doc = com_retry(lambda: spec.add_doc(app), timeout=timeout)
        hwnd = int(com_retry(lambda: spec.doc_hwnd(app, doc), timeout=timeout))
    except Exception:
        try:
            if _frame_pids(spec) - before or not before:
                app.Quit()
        finally:
            del app
            gc.collect()
        raise
    pid = win32.window_pid(hwnd)
    h = SandboxHandle(app, doc, hwnd, pid, created_instance=pid not in before, spec=spec)
    try:
        scale = win32.dpi_for_window(hwnd) / 96
        win32.place_window(hwnd, pos[0], pos[1], round(size_logical[0] * scale), round(size_logical[1] * scale))
        if fixture_id:
            fx = load_fixture(fixture_id)
            com_retry(lambda: spec.fill(doc, fx), timeout=timeout)
        if h.created_instance:  # crash recovery ledger (Phase 5)
            from . import recovery
            recovery.record(spec.name, pid, spec.frame_class, _caption_prefix(spec, doc))
        log.info("sandbox.setup", app=spec.name, pid=pid, hwnd=hwnd, created=h.created_instance,
                 seconds=round(time.monotonic() - t0, 2))
    except Exception:
        teardown(h)
        raise
    return h


def _caption_prefix(spec: AppSpec, doc) -> str:
    """The frame caption starts with the document name ("Book1", "Document1", "Presentation1")."""
    try:
        return str(doc.Name).rsplit(".", 1)[0]
    except Exception:
        return spec.name


def select(h: SandboxHandle, ref: str, timeout: float = 5.0) -> None:
    com_retry(lambda: h.spec.select(h.doc, ref), timeout=timeout)


def ping(h: SandboxHandle, timeout: float = 1.0):
    return com_retry(lambda: h.spec.ping(h.app), timeout=timeout)


def sandbox_windows(h: SandboxHandle) -> list[int]:
    """Visible top-level windows of the sandbox process, minus border-effect shadows. The process is
    ours alone (Excel/Word: own instance; PowerPoint: refused when already running)."""
    return [w for w in win32.top_level_windows(h.pid) if win32.class_name(w) != win32.BORDER_EFFECT_CLASS]


def dialogs(h: SandboxHandle) -> list[int]:
    return [w for w in sandbox_windows(h) if win32.class_name(w) in h.spec.dialog_classes]


def edit_hwnd(h: SandboxHandle) -> int:
    for c in win32.child_windows(h.hwnd):
        if win32.class_name(c) == h.spec.edit_child_class:
            return c
    return h.hwnd


def unstick(h: SandboxHandle) -> None:
    """Close our own modal dialogs/menus and leave edit mode so COM answers again (S4)."""
    if not h.created_instance:
        return  # never touch windows of an instance we did not create
    for w in dialogs(h):
        win32.post_close(w)
    win32.post_escape(edit_hwnd(h))
    time.sleep(0.4)


def teardown(h: SandboxHandle, exit_timeout: float = 15.0) -> dict:
    """Idempotent. Close without saving, quit only our own instance, release COM refs."""
    report = {"app": h.spec.name if h.spec else "?", "pid": h.pid, "closed_doc": False, "quit": False,
              "process_exited": None, "forced": False}
    if h.closed:
        return report
    h.closed = True
    try:
        unstick(h)
        com_retry(lambda: h.spec.close_doc(h.doc), timeout=8, on_busy=lambda: unstick(h))
        report["closed_doc"] = True
    except Exception as e:
        log.warning("sandbox.close_failed", error=repr(e))
    try:
        if h.created_instance and com_retry(lambda: h.spec.doc_count(h.app), timeout=5) == 0:
            com_retry(lambda: h.app.Quit(), timeout=5)
            report["quit"] = True
    except Exception as e:
        log.warning("sandbox.quit_failed", error=repr(e))
    h.doc = h.app = None
    gc.collect()  # Office only exits once every COM reference is released (S2)
    if h.created_instance:
        deadline = time.monotonic() + exit_timeout
        while win32.process_alive(h.pid) and time.monotonic() < deadline:
            time.sleep(0.25)
        if win32.process_alive(h.pid) and not report["closed_doc"]:
            # Last resort, only for an instance we created that holds nothing but the sandbox doc.
            report["forced"] = win32.terminate_process(h.pid)
            for _ in range(20):
                if not win32.process_alive(h.pid):
                    break
                time.sleep(0.25)
        report["process_exited"] = not win32.process_alive(h.pid)
        if report["process_exited"]:
            from . import recovery
            recovery.forget(h.pid)
    log.info("sandbox.teardown", **report)
    return report
