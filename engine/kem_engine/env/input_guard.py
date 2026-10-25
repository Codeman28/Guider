"""Stop a demonstration as soon as the user touches the mouse or keyboard.

Guider itself never synthesises input — it acts through UI Automation patterns, PostMessage and COM — so any change
in the system's last-input time comes from the person at the machine. A small mouse drift is tolerated; a real
move, any click or any key stops the run.
"""
from __future__ import annotations

import ctypes
import math
import threading
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
VK_MOUSE_BUTTONS = (0x01, 0x02, 0x04, 0x05, 0x06)  # left, right, middle, X1, X2
MOVE_PX = 60  # cumulative cursor travel that counts as "the user is using the mouse"


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def last_input_tick() -> int:
    li = _LASTINPUTINFO(ctypes.sizeof(_LASTINPUTINFO), 0)
    user32.GetLastInputInfo(ctypes.byref(li))
    return li.dwTime


def cursor() -> tuple[int, int]:
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def mouse_button_down() -> bool:
    return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in VK_MOUSE_BUTTONS)


class InputGuard:
    """Sets `cancel` when the user moves the mouse far, clicks or types. Use as a context manager."""

    def __init__(self, cancel: threading.Event, move_px: int = MOVE_PX, interval: float = 0.1, grace: float = 1.5):
        self.cancel = cancel
        self.move_px = move_px
        self.interval = interval
        self.grace = grace  # the Enter/click that started the run is still being released: ignore it
        self.reason: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self):
        self._tick, self._origin = last_input_tick(), cursor()
        self._last = self._origin
        self._until = time.monotonic() + self.grace
        self._thread = threading.Thread(target=self._run, name="input-guard", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join(1.0)

    def check(self, tick: int, pos: tuple[int, int], button: bool) -> str | None:
        """One observation → reason to stop, or None. Separate from the thread so it can be tested."""
        if tick == self._tick:
            return None
        if button:
            return "bấm chuột"
        if math.hypot(pos[0] - self._origin[0], pos[1] - self._origin[1]) > self.move_px:
            return "di chuột"  # travel from the start, so a slow drag still counts
        if pos == self._last:
            return "gõ phím"  # new input but the cursor did not move
        self._tick, self._last = tick, pos  # small drift: tolerated
        return None

    def _run(self):
        while not self._stop.wait(self.interval):
            if time.monotonic() < self._until:  # still in the grace period: move the reference along
                self._tick, self._origin = last_input_tick(), cursor()
                self._last = self._origin
                continue
            reason = self.check(last_input_tick(), cursor(), mouse_button_down())
            if reason:
                self.reason = reason
                self.cancel.set()
                return
