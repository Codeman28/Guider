"""Real keystrokes for keyboard-first demonstrations: typed Excel formulas and
shortcuts before ribbon hunting.

SendInput goes to whatever window is in front, so every send is preceded by a foreground check against the
sandbox windows (SafetyGuard, SPEC §8) and is short. The InputGuard is told that the next input is Guider's
own, so it does not mistake it for the user touching the machine.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from . import input_guard

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):  # only for the union's size
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


VK = {"ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "enter": 0x0D, "return": 0x0D, "tab": 0x09,
      "esc": 0x1B, "escape": 0x1B, "space": 0x20, "home": 0x24, "end": 0x23, "left": 0x25, "up": 0x26,
      "right": 0x27, "down": 0x28, "delete": 0x2E, "del": 0x2E, "backspace": 0x08, "pageup": 0x21,
      "pagedown": 0x22, "insert": 0x2D, ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF,
      "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE}
VK.update({f"f{i}": 0x6F + i for i in range(1, 13)})
SHIFTED = {"%": "5", "$": "4", "#": "3", "!": "1", "@": "2", "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
           "+": "=", ">": ".", "<": ",", ":": ";", "_": "-", "?": "/", "~": "`", "{": "[", "}": "]", "\"": "'"}
MODIFIERS = {"ctrl", "control", "shift", "alt"}
# Combos that act on Windows itself, not the Office window in front: never sent (a learned card once had
# Ctrl+Esc, which opens the Start menu).
SYSTEM = [{0x11, 0x1B}, {0x11, 0x10, 0x1B}, {0x12, 0x09}, {0x12, 0x1B}, {0x12, 0x73}, {0x12, 0x20}, {0x11, 0x12, 0x2E}]


class KeyComboError(ValueError):
    pass


def parse_combo(combo: str) -> list[int]:
    """'Ctrl+Shift+L' → [VK_CONTROL, VK_SHIFT, 'L']; 'Ctrl+Shift+%' → [ctrl, shift, '5']; 'Alt+=' works."""
    raw = combo.replace(" ", "")
    parts = [p for p in raw.split("+") if p] if raw != "+" else ["+"]
    if raw.endswith("++"):  # "Ctrl++" means the plus key
        parts = [p for p in raw[:-2].split("+") if p] + ["+"]
    keys: list[int] = []
    for p in parts:
        lp = p.lower()
        if lp in SHIFTED or (len(p) == 1 and p in SHIFTED):
            if 0x10 not in keys:
                keys.append(0x10)
            lp = SHIFTED[p]
        if lp in VK:
            keys.append(VK[lp])
        elif len(lp) == 1 and lp.isalnum():
            keys.append(ord(lp.upper()))
        else:
            raise KeyComboError(f"không hiểu phím {p!r} trong {combo!r}")
    if not keys or all(k in (0x10, 0x11, 0x12) for k in keys):
        raise KeyComboError(f"tổ hợp phím rỗng: {combo!r}")
    if set(keys) in SYSTEM:
        raise KeyComboError(f"{combo!r} là phím tắt của Windows, không phải của Office")
    return keys


def _send(inputs: list[INPUT]) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    input_guard.mark_self_input()
    if user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT)) != len(inputs):
        raise OSError(ctypes.get_last_error(), "SendInput failed")
    input_guard.mark_self_input()


def _key(vk: int, up: bool) -> INPUT:
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP if up else 0,
                                                    time=0, dwExtraInfo=0))


def press(combo: str) -> None:
    keys = parse_combo(combo)
    _send([_key(k, False) for k in keys] + [_key(k, True) for k in reversed(keys)])


def type_text(text: str, check_foreground=None, chunk: int = 8, delay: float = 0.02) -> None:
    """Unicode typing, a few characters at a time; `check_foreground()` runs before each chunk and must raise
    if the sandbox is no longer in front (the user switched windows)."""
    for i in range(0, len(text), chunk):
        if check_foreground is not None:
            check_foreground()
        events: list[INPUT] = []
        for ch in text[i:i + chunk]:
            raw = ch.encode("utf-16-le")
            for j in range(0, len(raw), 2):  # one or two UTF-16 units per character
                unit = int.from_bytes(raw[j:j + 2], "little")
                for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
                    events.append(INPUT(type=INPUT_KEYBOARD,
                                        ki=KEYBDINPUT(wVk=0, wScan=unit, dwFlags=flags, time=0, dwExtraInfo=0)))
        _send(events)
        time.sleep(delay)


def bring_to_front(hwnd: int, tries: int = 3) -> bool:
    """Make the sandbox the foreground window without pressing Alt (Alt shows KeyTips in the screenshots)."""
    for _ in range(tries):
        if user32.GetForegroundWindow() == hwnd:
            return True
        fg = user32.GetForegroundWindow()
        cur = ctypes.windll.kernel32.GetCurrentThreadId()
        fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        if fg_thread and fg_thread != cur:
            user32.AttachThreadInput(cur, fg_thread, True)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if fg_thread and fg_thread != cur:
            user32.AttachThreadInput(cur, fg_thread, False)
        time.sleep(0.15)
        if user32.GetForegroundWindow() != hwnd:
            user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE then SW_RESTORE: Windows gives the restored window focus
            user32.ShowWindow(hwnd, 9)
            time.sleep(0.3)
    return user32.GetForegroundWindow() == hwnd
