"""Thin ctypes layer over the Win32 calls the engine needs. Import only on Windows."""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

_PMV2 = ctypes.c_void_p(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
WM_CLOSE = 0x0010
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
VK_ESCAPE = 0x1B
BORDER_EFFECT_CLASS = "MSO_BORDEREFFECT_WINDOW_CLASS"


def set_dpi_awareness() -> bool:
    """Must run before any UIA/window call (SPEC §6.2, verified in S5)."""
    try:
        return bool(user32.SetProcessDpiAwarenessContext(_PMV2))
    except AttributeError:
        return False


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def window_text(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def is_window(hwnd: int) -> bool:
    return bool(user32.IsWindow(hwnd))


def top_level_windows(pid: int | None = None) -> list[int]:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and (pid is None or window_pid(hwnd) == pid):
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found


def child_windows(hwnd: int) -> list[int]:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        found.append(h)
        return True

    user32.EnumChildWindows(hwnd, cb, 0)
    return found


def foreground() -> int:
    return user32.GetForegroundWindow() or 0


def place_window(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    user32.ShowWindow(hwnd, 9)
    user32.MoveWindow(hwnd, x, y, w, h, True)


def post_close(hwnd: int) -> None:
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def post_escape(hwnd: int) -> None:
    user32.PostMessageW(hwnd, WM_KEYDOWN, VK_ESCAPE, 0)
    user32.PostMessageW(hwnd, WM_KEYUP, VK_ESCAPE, 0)


def dpi_for_window(hwnd: int) -> int:
    return user32.GetDpiForWindow(hwnd)


def screen_size() -> tuple[int, int]:
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def escape_pressed() -> bool:
    """Global Esc (SPEC §8): true if Esc went down since the last call."""
    return bool(user32.GetAsyncKeyState(VK_ESCAPE) & 0x8001)


def process_alive(pid: int) -> bool:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    SYNCHRONIZE = 0x00100000
    h = k32.OpenProcess(SYNCHRONIZE, False, pid)
    if not h:
        return False
    try:
        return k32.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT
    finally:
        k32.CloseHandle(h)


def terminate_process(pid: int) -> bool:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    PROCESS_TERMINATE = 0x0001
    h = k32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not h:
        return False
    try:
        return bool(k32.TerminateProcess(h, 1))
    finally:
        k32.CloseHandle(h)
