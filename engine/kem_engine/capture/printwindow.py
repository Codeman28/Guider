"""Capturer (SPEC §6.6). PrintWindow + PW_RENDERFULLCONTENT (S3: required; works when partly covered).

Ribbon popups and dialogs are separate top-level windows; they are captured one by one and pasted
at their screen offset onto the main window image (S3: 0.02/255 mean diff vs the real screen).
"""
from __future__ import annotations

from ..env import win32

PW_RENDERFULLCONTENT = 0x2  # undocumented; Chromium/WebRTC rely on it


def capture_window(hwnd: int):
    import win32gui
    import win32ui
    from PIL import Image

    l, t, r, b = win32.window_rect(hwnd)
    w, h = r - l, b - t
    if w <= 0 or h <= 0:
        raise RuntimeError("window has no area (minimized?)")
    hdc = win32gui.GetWindowDC(hwnd)
    src = win32ui.CreateDCFromHandle(hdc)
    mem = src.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(src, w, h)
    mem.SelectObject(bmp)
    try:
        if not win32.user32.PrintWindow(hwnd, mem.GetSafeHdc(), PW_RENDERFULLCONTENT):
            raise RuntimeError("PrintWindow failed")
        info = bmp.GetInfo()
        img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bmp.GetBitmapBits(True),
                               "raw", "BGRX", 0, 1).copy()
    finally:
        win32gui.DeleteObject(bmp.GetHandle())
        mem.DeleteDC()
        src.DeleteDC()
        win32gui.ReleaseDC(hwnd, hdc)
    return img, (l, t, r, b)


def capture_composite(main_hwnd: int, extra_hwnds: list[int]):
    """Main window image with popups/dialogs pasted in place. Returns (image, origin_xy)."""
    base, (l, t, _, _) = capture_window(main_hwnd)
    # paste back to front (EnumWindows lists top-most first), so a dialog opened from another dialog lands on
    # top of it, as on screen (Format Cells over New Formatting Rule, 10/11/2026)
    z = {h: i for i, h in enumerate(win32.top_level_windows())}
    for h in sorted(extra_hwnds, key=lambda h: -z.get(h, -1)):
        if h == main_hwnd or not win32.is_window(h):
            continue
        try:
            img, (pl, pt, _, _) = capture_window(h)
        except RuntimeError:
            continue
        base.paste(img, (pl - l, pt - t))
    return base, (l, t)
