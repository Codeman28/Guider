"""Env Probe (SPEC §6.2) — no LLM."""
from __future__ import annotations

import re

from ..models import EnvProfile
from . import win32

MSO_LANGUAGE_ID_UI = 2  # MsoAppLanguageID.msoLanguageIDUI — S6: Install/ExeMode differ from UI
LCID_TAGS = {1033: "en-US", 1066: "vi-VN"}


def normalize_build(raw: str) -> str:
    """'20326.0' / '16.0.20326' / '20326' → '20326' (S6: format differs per app)."""
    nums = [p for p in re.split(r"\D+", str(raw)) if p]
    big = [p for p in nums if len(p) >= 4]
    return big[0] if big else (nums[-1] if nums else "unknown")


def probe_excel(app, hwnd: int) -> EnvProfile:
    lcid = int(app.LanguageSettings.LanguageID(MSO_LANGUAGE_ID_UI))
    try:
        build = str(app.Build)
    except Exception:
        build = "unknown"
    dpi = win32.dpi_for_window(hwnd)
    return EnvProfile(app="excel", office_version=str(app.Version), office_build=normalize_build(build),
                      ui_lang=LCID_TAGS.get(lcid, f"lcid-{lcid}"), ui_lcid=lcid, dpi=dpi,
                      scale_pct=round(dpi / 96 * 100), screen=win32.screen_size())
