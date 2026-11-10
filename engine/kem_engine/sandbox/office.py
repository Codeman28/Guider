"""Office sandbox core (SPEC §6.3): a private, never-saved document in Excel, Word or PowerPoint.

Each app is an AppSpec: how to add the blank document, find its window, fill a fixture, select a
reference, close without saving. The lifecycle (setup / unstick / teardown) is shared and keeps the
guarantees proven in Phase 0–2: COM retry while Office is busy, Esc before closing, quit only our own
instance, release every COM reference so the process exits.

User-file mode (SPEC v1.3 §8, ADR-0003): the user picks a file in the app; it is copied into
%LOCALAPPDATA%/Kem/work/<id>/ and only the copy is opened (macros off, no link updates, not added to
recent files). The original is never opened by Office. The copy is deleted at teardown.
"""
from __future__ import annotations

import gc
import json
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import structlog

from ..env import win32
from .com import com_retry

log = structlog.get_logger()

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
MSO_AUTOMATION_SECURITY_FORCE_DISABLE = 3  # MsoAutomationSecurity: open with macros disabled
USER_FILE_TYPES = {".xlsx": "excel", ".xlsm": "excel", ".xls": "excel", ".csv": "excel",
                   ".docx": "word", ".docm": "word", ".doc": "word",
                   ".pptx": "powerpoint", ".pptm": "powerpoint", ".ppt": "powerpoint"}
MAX_USER_FILE_BYTES = 200 * 1024 * 1024


def work_root() -> Path:
    if os.environ.get("KEM_WORK"):  # tests / sandboxed shells where Office cannot see %LOCALAPPDATA% writes
        return Path(os.environ["KEM_WORK"])
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Kem" / "work"


def app_for_file(path: str | Path) -> str | None:
    return USER_FILE_TYPES.get(Path(path).suffix.lower())


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
    open_doc: Callable[[Any, str], Any] | None = None  # user-file mode: open the private copy
    map_ref: Callable[[Any, str], str] | None = None  # card ref (fixture layout) → ref in the user's file
    deselect: Callable[[Any], None] | None = None  # before the final screenshot: selection shading hides results


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
    work_dir: Path | None = None  # user-file mode: folder holding the private copy (deleted at teardown)
    ribbon_was_minimized: bool = False  # the user's "Show tabs only" choice, put back at teardown
    sample: bool = False  # filled from a sample rebuilt from the user's picture (ADR-0005), not the card's fixture

    @property
    def user_file(self) -> bool:
        return self.work_dir is not None

    @property
    def adapt_refs(self) -> bool:
        """Card refs describe the card's fixture; on the user's file or a rebuilt sample they are mapped."""
        return self.user_file or self.sample


def load_fixture(fixture_id: str) -> dict:
    path = FIXTURES / f"{fixture_id}.json"
    if re.fullmatch(r"card_[a-z0-9_]+", fixture_id or ""):  # built for one learned card (training/refit.py)
        path = FIXTURES / "cards" / f"{fixture_id}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    if path.parent != FIXTURES or not path.exists():  # fixture IDs only, never arbitrary paths
        raise ValueError(f"unknown fixture {fixture_id!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def _frame_pids(spec: AppSpec) -> set[int]:
    return {win32.window_pid(h) for h in win32.top_level_windows() if win32.class_name(h) == spec.frame_class}


def copy_user_file(source: str | Path) -> tuple[Path, Path]:
    """Copy the user's file into a fresh work folder; returns (work_dir, copy). Never touches the original."""
    src = Path(source)
    if app_for_file(src) is None or not src.is_file():
        raise ValueError("Guider chỉ làm mẫu trên file Excel, Word hoặc PowerPoint có thật trên máy.")
    if src.stat().st_size > MAX_USER_FILE_BYTES:
        raise ValueError("File quá lớn để Guider làm mẫu (tối đa 200 MB).")
    work = work_root() / uuid.uuid4().hex[:12]
    work.mkdir(parents=True)
    dst = work / src.name
    shutil.copy2(src, dst)  # Office may hold the original open; a read-only copy still works
    os.chmod(dst, 0o666)    # the copy must be writable even if the original is read-only
    return work, dst


def setup(spec: AppSpec, fixture_id: str | None, size_logical=(1280, 800), pos=(40, 40),
          timeout: float = 60.0, source_file: str | Path | None = None,
          fixture: dict | None = None) -> SandboxHandle:
    """fixture: a ready fixture dict (a sample rebuilt from the user's picture) used instead of fixture_id."""
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
    work = copy = None
    if source_file is not None:
        if spec.open_doc is None:
            raise SandboxRefused(f"{spec.name} chưa hỗ trợ làm mẫu trên file của bạn.")
        work, copy = copy_user_file(source_file)
    app = win32com.client.DispatchEx(spec.progid)
    try:
        com_retry(lambda: setattr(app, "Visible", True), timeout=timeout)
        if copy is not None:
            com_retry(lambda: setattr(app, "AutomationSecurity", MSO_AUTOMATION_SECURITY_FORCE_DISABLE), timeout=timeout)
            doc = com_retry(lambda: spec.open_doc(app, str(copy)), timeout=timeout)
        else:
            doc = com_retry(lambda: spec.add_doc(app), timeout=timeout)
        hwnd = int(com_retry(lambda: spec.doc_hwnd(app, doc), timeout=timeout))
    except Exception:
        try:
            if _frame_pids(spec) - before or not before:
                app.Quit()
        finally:
            del app
            gc.collect()
            if work is not None:
                shutil.rmtree(work, ignore_errors=True)
        raise
    pid = win32.window_pid(hwnd)
    h = SandboxHandle(app, doc, hwnd, pid, created_instance=pid not in before, spec=spec, work_dir=work)
    try:
        scale = win32.dpi_for_window(hwnd) / 96
        win32.place_window(hwnd, pos[0], pos[1], round(size_logical[0] * scale), round(size_logical[1] * scale))
        if fixture is not None and copy is None:
            h.sample = True
            com_retry(lambda: spec.fill(doc, fixture), timeout=timeout)
        elif fixture_id and copy is None:
            fx = load_fixture(fixture_id)
            com_retry(lambda: spec.fill(doc, fx), timeout=timeout)
        expand_ribbon(h)
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
    if h.adapt_refs and h.spec.map_ref is not None:  # card refs describe the fixture; adapt to the real file
        ref = com_retry(lambda: h.spec.map_ref(h.doc, ref), timeout=timeout)
    com_retry(lambda: h.spec.select(h.doc, ref), timeout=timeout)


def deselect(h: SandboxHandle, timeout: float = 3.0) -> None:
    if h.spec.deselect is not None:
        com_retry(lambda: h.spec.deselect(h.doc), timeout=timeout)


def ping(h: SandboxHandle, timeout: float = 1.0):
    return com_retry(lambda: h.spec.ping(h.app), timeout=timeout)


def sandbox_windows(h: SandboxHandle) -> list[int]:
    """Visible top-level windows of the sandbox process, minus border-effect shadows. The process is
    ours alone (Excel/Word: own instance; PowerPoint: refused when already running)."""
    return [w for w in win32.top_level_windows(h.pid) if win32.class_name(w) != win32.BORDER_EFFECT_CLASS]


def expand_ribbon(h: SandboxHandle) -> None:
    """A minimized ribbon ("Show tabs only", saved in the user's Office settings) opens each tab as a flyout that
    closes as soon as focus moves, taking its menus and buttons with it. Show the full ribbon while Guider works;
    restore_ribbon puts the user's choice back before Office quits (the setting is saved on exit)."""
    try:
        bars = h.app.CommandBars
        if bars.GetPressedMso("MinimizeRibbon"):
            bars.ExecuteMso("MinimizeRibbon")
            h.ribbon_was_minimized = True
    except Exception as e:
        log.warning("sandbox.ribbon_expand_failed", error=repr(e))


def restore_ribbon(h: SandboxHandle) -> None:
    if not h.ribbon_was_minimized:
        return
    try:
        bars = h.app.CommandBars
        if not bars.GetPressedMso("MinimizeRibbon"):
            bars.ExecuteMso("MinimizeRibbon")
        h.ribbon_was_minimized = False
    except Exception as e:
        log.warning("sandbox.ribbon_restore_failed", error=repr(e))


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
        restore_ribbon(h)
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
    if h.work_dir is not None:  # the private copy of the user's file (only this folder, never the original)
        for _ in range(20):
            shutil.rmtree(h.work_dir, ignore_errors=True)
            if not h.work_dir.exists():
                break
            time.sleep(0.25)
        report["copy_deleted"] = not h.work_dir.exists()
    log.info("sandbox.teardown", **report)
    return report
