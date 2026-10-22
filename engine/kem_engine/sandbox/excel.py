"""Excel sandbox (SPEC §6.3): a private instance with one blank, never-saved workbook."""
from __future__ import annotations

import gc
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from ..env import win32
from .com import com_retry

log = structlog.get_logger()

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
DIALOG_CLASSES = ("NUIDialog", "bosa_sdm_XL9", "#32770")


@dataclass
class SandboxHandle:
    app: object
    doc: object
    hwnd: int
    pid: int
    created_instance: bool
    created_at: float = field(default_factory=time.time)
    closed: bool = False


def load_fixture(fixture_id: str) -> dict:
    path = FIXTURES / f"{fixture_id}.json"
    if path.parent != FIXTURES or not path.exists():  # fixture IDs only, never arbitrary paths
        raise ValueError(f"unknown fixture {fixture_id!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def _excel_pids() -> set[int]:
    return {win32.window_pid(h) for h in win32.top_level_windows() if win32.class_name(h) == "XLMAIN"}


def setup(fixture_id: str | None, size_logical=(1280, 800), pos=(40, 40),
          timeout: float = 60.0) -> SandboxHandle:
    from ..env import runtime
    runtime.init()  # COM apartment must be set by the UIA stack first
    import win32com.client

    before = _excel_pids()
    t0 = time.monotonic()
    app = win32com.client.DispatchEx("Excel.Application")
    try:
        # Excel rejects calls while it is still starting (RPC_E_CALL_REJECTED)
        com_retry(lambda: setattr(app, "Visible", True), timeout=timeout)
        com_retry(lambda: setattr(app, "DisplayAlerts", False), timeout=timeout)
        doc = com_retry(lambda: app.Workbooks.Add(), timeout=timeout)
        hwnd = int(com_retry(lambda: app.Hwnd, timeout=timeout))
    except Exception:
        try:
            if _excel_pids() - before or not before:
                app.Quit()
        finally:
            del app
            gc.collect()
        raise
    pid = win32.window_pid(hwnd)
    h = SandboxHandle(app, doc, hwnd, pid, created_instance=pid not in before)
    try:
        scale = win32.dpi_for_window(hwnd) / 96
        win32.place_window(hwnd, pos[0], pos[1], round(size_logical[0] * scale), round(size_logical[1] * scale))
        if fixture_id:
            fx = load_fixture(fixture_id)
            rows = [fx["columns"]] + fx["rows"]
            ws = doc.Worksheets(1)
            ref = f"A1:{chr(ord('A') + len(fx['columns']) - 1)}{len(rows)}"
            ws.Range(ref).Value = rows
            ws.Range("A1").Select()
        log.info("sandbox.setup", pid=pid, hwnd=hwnd, created=h.created_instance,
                 seconds=round(time.monotonic() - t0, 2))
    except Exception:
        teardown(h)
        raise
    return h


def sandbox_windows(h: SandboxHandle) -> list[int]:
    """Visible top-level windows of the sandbox process, minus border-effect shadows."""
    return [w for w in win32.top_level_windows(h.pid) if win32.class_name(w) != win32.BORDER_EFFECT_CLASS]


def dialogs(h: SandboxHandle) -> list[int]:
    return [w for w in sandbox_windows(h) if win32.class_name(w) in DIALOG_CLASSES]


def grid_hwnd(h: SandboxHandle) -> int:
    for c in win32.child_windows(h.hwnd):
        if win32.class_name(c) == "EXCEL7":
            return c
    return h.hwnd


def unstick(h: SandboxHandle) -> None:
    """Close our own modal dialogs/menus and leave cell-edit mode so COM answers again (S4)."""
    if not h.created_instance:
        return  # never touch windows of an instance we did not create
    for w in dialogs(h):
        win32.post_close(w)
    win32.post_escape(grid_hwnd(h))
    time.sleep(0.4)


def teardown(h: SandboxHandle, exit_timeout: float = 15.0) -> dict:
    """Idempotent. Close without saving, quit only our own instance, release COM refs."""
    report = {"pid": h.pid, "closed_doc": False, "quit": False, "process_exited": None, "forced": False}
    if h.closed:
        return report
    h.closed = True
    try:
        unstick(h)
        com_retry(lambda: h.doc.Close(SaveChanges=False), timeout=8, on_busy=lambda: unstick(h))
        report["closed_doc"] = True
    except Exception as e:
        log.warning("sandbox.close_failed", error=repr(e))
    try:
        if h.created_instance and com_retry(lambda: h.app.Workbooks.Count, timeout=5) == 0:
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
    log.info("sandbox.teardown", **report)
    return report
