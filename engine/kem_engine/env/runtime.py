"""Process-wide init. Order matters and must run before anything touches COM or windows:

1. Per-Monitor V2 DPI awareness (S5).
2. Import pywinauto/comtypes UIA: it sets sys.coinit_flags=0 (MTA). If pywin32 initialized COM first
   (STA), the Excel proxy dies with "Object is not connected to server" after the first UIA query
   (found in Phase 1).
"""
from __future__ import annotations

_done = False


def init() -> None:
    global _done
    if _done:
        return
    from . import win32
    win32.set_dpi_awareness()
    from ..uia.snapshot import _iuia
    _iuia()
    _done = True
