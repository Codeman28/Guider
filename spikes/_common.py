"""Shared helpers for Phase 0 spikes.

Spikes only ever touch documents they create themselves (SPEC §8, §15):
every Office instance is opened with DispatchEx, the HWND whitelist is derived
from that instance, and teardown closes without saving.
"""
from __future__ import annotations

import ctypes
import json
import os
import time
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "spikes" / "out"
OUT.mkdir(parents=True, exist_ok=True)

user32 = ctypes.WinDLL("user32", use_last_error=True)

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == (HANDLE)-4
_PMV2 = ctypes.c_void_p(-4)


def set_dpi_awareness() -> str:
    """Must run before any window/UIA call (SPEC §6.2)."""
    try:
        if user32.SetProcessDpiAwarenessContext(_PMV2):
            return "PerMonitorV2"
        err = ctypes.get_last_error()
        # ERROR_ACCESS_DENIED: already set (e.g. by comtypes/pywinauto import)
        return f"SetProcessDpiAwarenessContext failed (err={err})"
    except AttributeError:
        return "unsupported"


def current_dpi_awareness() -> int:
    ctx = user32.GetThreadDpiAwarenessContext()
    return user32.GetAwarenessFromDpiAwarenessContext(ctypes.c_void_p(ctx))


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def dpi_for_window(hwnd: int) -> int:
    return user32.GetDpiForWindow(hwnd)


def top_level_windows(pid: int | None = None, visible_only: bool = True) -> list[int]:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if visible_only and not user32.IsWindowVisible(hwnd):
            return True
        if pid is None or window_pid(hwnd) == pid:
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found


def class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def owner_of(hwnd: int) -> int:
    GW_OWNER = 4
    return user32.GetWindow(hwnd, GW_OWNER) or 0


def office_pids(exe: str) -> set[int]:
    import subprocess

    out = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {exe}", "/FO", "CSV", "/NH"],
        capture_output=True, text=True,
    ).stdout
    pids = set()
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            pids.add(int(parts[1]))
    return pids


APPS = {
    "excel": ("Excel.Application", "EXCEL.EXE"),
    "word": ("Word.Application", "WINWORD.EXE"),
    "powerpoint": ("PowerPoint.Application", "POWERPNT.EXE"),
}


@dataclass
class Sandbox:
    app_name: str
    app: object
    doc: object
    hwnd: int
    pid: int
    created_instance: bool
    pre_existing_pids: set[int] = field(default_factory=set)


def _doc_hwnd(app_name: str, app, doc) -> int:
    if app_name == "excel":
        return int(app.Hwnd)
    if app_name == "word":
        return int(doc.ActiveWindow.Hwnd)
    # PowerPoint exposes no HWND over COM on this build ("Member not found" for
    # Application.HWND and DocumentWindow.HWND, late- and early-bound). Find the
    # frame window whose caption starts with the presentation name.
    title = str(doc.Name)
    for _ in range(20):
        for h in top_level_windows():
            if class_name(h) == "PPTFrameClass" and window_text(h).startswith(title):
                return h
        time.sleep(0.25)
    raise RuntimeError(f"PowerPoint frame for {title!r} not found")


def window_text(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def open_sandbox(app_name: str, size=(1280, 800), pos=(40, 40)) -> Sandbox:
    import win32com.client

    progid, exe = APPS[app_name]
    before = office_pids(exe)
    app = win32com.client.DispatchEx(progid)
    app.Visible = True
    if app_name == "excel":
        doc = app.Workbooks.Add()
    elif app_name == "word":
        doc = app.Documents.Add()
    else:
        doc = app.Presentations.Add(True)  # WithWindow=msoTrue
        doc.Slides.Add(1, 1)  # ppLayoutTitle
    time.sleep(1.0)
    sb = Sandbox(app_name, app, doc, 0, 0, False, before)
    try:
        sb.hwnd = _doc_hwnd(app_name, app, doc)
        sb.pid = window_pid(sb.hwnd)
        sb.created_instance = sb.pid not in before
        place_window(sb.hwnd, pos, size)
    except Exception:
        sb.created_instance = not before or bool(office_pids(exe) - before)
        close_sandbox(sb)
        raise
    return sb


def place_window(hwnd: int, pos, size) -> None:
    SW_RESTORE = 9
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.MoveWindow(hwnd, pos[0], pos[1], size[0], size[1], True)
    time.sleep(0.5)


def close_sandbox(sb: Sandbox) -> None:
    """Idempotent: close doc without saving; quit only instances we created."""
    try:
        if sb.app_name == "excel":
            sb.doc.Close(SaveChanges=False)
        elif sb.app_name == "word":
            sb.doc.Close(SaveChanges=0)  # wdDoNotSaveChanges
        else:
            sb.doc.Saved = True
            sb.doc.Close()
    except Exception as e:  # already closed
        print("close doc:", e)
    try:
        remaining = {
            "excel": lambda a: a.Workbooks.Count,
            "word": lambda a: a.Documents.Count,
            "powerpoint": lambda a: a.Presentations.Count,
        }[sb.app_name](sb.app)
        if sb.created_instance and remaining == 0:
            sb.app.Quit()
    except Exception as e:
        print("quit:", e)
    sb.app = sb.doc = None


@contextmanager
def sandbox(app_name: str, **kw):
    sb = open_sandbox(app_name, **kw)
    try:
        yield sb
    finally:
        close_sandbox(sb)


def foreground() -> int:
    return user32.GetForegroundWindow()


def force_foreground(hwnd: int) -> bool:
    # Alt-key trick lets a background process take foreground for its own window.
    VK_MENU, KEYUP = 0x12, 0x2
    user32.keybd_event(VK_MENU, 0, 0, 0)
    ok = bool(user32.SetForegroundWindow(hwnd))
    user32.keybd_event(VK_MENU, 0, KEYUP, 0)
    time.sleep(0.3)
    return ok


PW_RENDERFULLCONTENT = 0x2  # undocumented; used by Chromium/WebRTC


def print_window(hwnd: int, flags: int = PW_RENDERFULLCONTENT):
    """Capture one window via PrintWindow → PIL.Image (physical px under PMv2)."""
    import win32gui
    import win32ui
    from PIL import Image

    l, t, r, b = window_rect(hwnd)
    w, h = r - l, b - t
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    src = win32ui.CreateDCFromHandle(hwnd_dc)
    mem = src.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(src, w, h)
    mem.SelectObject(bmp)
    ok = user32.PrintWindow(hwnd, mem.GetSafeHdc(), flags)
    info = bmp.GetInfo()
    img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]),
                           bmp.GetBitmapBits(True), "raw", "BGRX", 0, 1)
    win32gui.DeleteObject(bmp.GetHandle())
    mem.DeleteDC()
    src.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)
    return img, bool(ok), (l, t, r, b)


def screen_grab(box):
    from PIL import ImageGrab
    return ImageGrab.grab(bbox=box, all_screens=True)


def img_stats(img) -> dict:
    from PIL import ImageStat
    g = img.convert("L")
    st = ImageStat.Stat(g)
    lo, hi = g.getextrema()
    return {"mean": round(st.mean[0], 1), "stddev": round(st.stddev[0], 1), "min": lo, "max": hi,
            "blank": st.stddev[0] < 2.0}


def mean_abs_diff(a, b) -> float:
    from PIL import ImageChops, ImageStat
    if a.size != b.size:
        b = b.resize(a.size)
    d = ImageChops.difference(a.convert("L"), b.convert("L"))
    return round(ImageStat.Stat(d).mean[0], 2)


def launch_occluder(rect):
    """Our own Notepad window, used only to cover part of the sandbox. Returns (proc, hwnd)."""
    import subprocess
    before = set(top_level_windows())
    proc = subprocess.Popen(["notepad.exe"])
    hwnd = 0
    for _ in range(40):
        time.sleep(0.25)
        new = [h for h in top_level_windows() if h not in before and class_name(h) == "Notepad"]
        if new:
            hwnd = new[0]
            break
    if hwnd:
        user32.MoveWindow(hwnd, rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1], True)
        force_foreground(hwnd)
    return proc, hwnd


def close_occluder(proc, hwnd):
    WM_CLOSE = 0x10
    if hwnd:
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


def save_json(name: str, data) -> Path:
    p = OUT / f"{name}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return p


def env_summary() -> dict:
    import platform
    return {
        "python": platform.python_version(),
        "windows": platform.version(),
        "machine": os.environ.get("COMPUTERNAME", "?"),
    }
