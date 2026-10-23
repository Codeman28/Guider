"""Intent Router (SPEC §6.1), rule-based step. No LLM here: an unsure case goes to the Planner,
whose schema carries in_scope/reason, so routing never costs an extra call."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .knowledge import fold

APP_WORDS = {
    "excel": ["excel", "bang tinh", "trang tinh", "pivot", "cong thuc", "sheet", "o tinh", "cot", "o"],
    "word": ["word", "van ban", "doan van", "muc luc", "so trang", "tai lieu", "chu cai dau"],
    "powerpoint": ["powerpoint", "power point", "slide", "trang chieu", "trinh chieu", "ppt", "hieu ung",
                   "chuyen canh", "bai thuyet trinh"],
}

# Vietnamese words are matched WITH diacritics (folding would turn "tại sao" into "tải", "cái" into
# "cài"); English words are matched on folded text. (vi_pattern, en_pattern, reason)
OUT_OF_SCOPE = [
    (r"\b(tải|cài đặt|cài|bẻ khóa|bản quyền|mua|kích hoạt)\b", r"\b(download|install|crack|license|activate)\b",
     "Guider không tải, cài đặt hay kích hoạt phần mềm trên máy bạn, nên không làm mẫu được việc này."),
    (r"\b(gửi|thư điện tử)\b", r"\b(send|email|e mail|mail|outlook)\b",
     "Gửi thư hoặc gửi file là thao tác ra ngoài máy, Guider không làm mẫu."),
    (r"\b(chia sẻ|đồng bộ)\b", r"\b(share|onedrive|sharepoint|teams|sync)\b",
     "Chia sẻ hoặc đồng bộ lên mạng là thao tác ra ngoài máy, Guider không làm mẫu."),
    (r"\b(đăng nhập|đăng xuất|tài khoản|mật khẩu)\b", r"\b(sign in|sign out|login|account|password)\b",
     "Đăng nhập và tài khoản là dữ liệu cá nhân, Guider không đụng tới."),
    (r"\b(mã vba)\b", r"\b(macro|vba|visual basic)\b",
     "Macro/VBA có thể chạy mã tùy ý, Guider không làm mẫu phần này."),
    (r"(?!x)x", r"\b(copilot|chatgpt|gemini)\b",
     "Guider không điều khiển trợ lý AI khác trong Office."),
]
SUPPORTED_APPS = {"excel", "word", "powerpoint"}  # Phase 4


@dataclass
class Route:
    in_scope: bool
    app: str | None
    reason: str | None = None
    unsure_app: bool = False


def route(question: str, app_hint: str | None = None) -> Route:
    raw = unicodedata.normalize("NFC", question or "").lower()
    q = fold(question)
    for vi, en, reason in OUT_OF_SCOPE:
        if re.search(vi, raw) or re.search(en, q):
            return Route(False, None, reason)
    if app_hint:
        app, unsure = app_hint, False
    else:
        hits = {a: sum(f" {w} " in f" {q} " for w in words) for a, words in APP_WORDS.items()}
        best = max(hits, key=hits.get)
        app, unsure = (best, False) if hits[best] > 0 else ("excel", True)
    if app not in SUPPORTED_APPS:
        return Route(False, app, f"Guider hiện mới làm mẫu được trên Excel; {app.title()} sẽ có ở bản sau.")
    return Route(True, app, None, unsure)
