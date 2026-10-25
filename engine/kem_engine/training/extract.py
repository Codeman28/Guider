"""Chunk → candidate task cards + knowledge notes (LLM), then candidate → card grounded on the real ribbon.

The model proposes; real UIA names decide. A ribbon button the dump does not know is a hallucination and the
candidate is dropped. Names inside menus/galleries cannot be checked offline; the demonstration (verify.py) does.
"""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..grounding.grounder import expand_names, load_aliases, name_score
from ..intent.knowledge import fold

App = Literal["excel", "word", "powerpoint"]
Intent = Literal["select_ribbon_tab", "invoke", "expand", "select_item", "toggle", "set_value"]
CT = Literal["TabItem", "Button", "SplitButton", "MenuItem", "ListItem", "CheckBox", "ComboBox", "Edit"]
Selection = Literal["none", "table", "column_values", "header_row", "single_cell", "title", "heading", "body",
                    "paragraphs", "all", "title_slide", "content_slide", "slide_title", "slide_body"]

DUMPS = Path(__file__).resolve().parents[3] / "docs" / "spikes" / "out"
FIXTURE = {"excel": "sales_table_basic", "word": "word_report_basic", "powerpoint": "ppt_deck_basic"}
SELECT = {  # what the card selects in the fixture before step 1 (sandbox/*.py fixtures)
    "excel": {"table": "A1:D21", "column_values": "D2:D21", "header_row": "A1:D1", "single_cell": "D2"},
    "word": {"title": "p1", "heading": "p2", "body": "p3", "paragraphs": "p3-p5", "all": "all"},
    "powerpoint": {"title_slide": "s1", "content_slide": "s2", "slide_title": "s2.1", "slide_body": "s2.2"},
}


class XStep(BaseModel):
    intent: Intent
    names: list[str] = Field(description="Tên nút đúng như trên giao diện TIẾNG ANH của Microsoft 365, có thể thêm tên tiếng Việt sau")
    control_type: CT
    value: Optional[str] = None


class XTask(BaseModel):
    app: App
    title: str = Field(description="Tiêu đề tiếng Việt, dạng 'Cách ... trong Excel'")
    keywords: list[str] = Field(description="3–8 cách người dùng Việt hay hỏi việc này")
    selection: Selection
    steps: list[XStep]
    example: str = Field("", description="Ví dụ cụ thể 1–2 câu trên file mẫu: chọn gì, bấm gì, ra kết quả gì")


class XNote(BaseModel):
    app: App
    topic: str
    fact: str = Field(description="1–2 câu tiếng Việt, tự diễn đạt lại, không chép nguyên văn")


class XOut(BaseModel):
    summary: str = Field(description="2–3 câu tiếng Việt tóm tắt đoạn này")
    tasks: list[XTask]
    notes: list[XNote]


SYSTEM = (
    "Bạn đọc tài liệu hướng dẫn Microsoft 365 (Excel, Word, PowerPoint trên Windows) để dạy cho một trợ lý làm mẫu "
    "thao tác. Từ đoạn văn, rút ra: (1) các VIỆC làm được bằng chuỗi bấm nút trên ribbon, mỗi việc là một 'task' với "
    "các bước bấm theo đúng thứ tự; bước đầu luôn là select_ribbon_tab; dùng tên nút TIẾNG ANH chuẩn của Microsoft 365 "
    "(Home, Insert, Bold, Conditional Formatting...), expand cho nút mở menu/gallery, select_item cho mục trong "
    "menu/gallery, invoke cho nút bấm và nút OK, set_value để gõ giá trị vào ô của hộp thoại. Chỉ lấy việc làm được "
    "trên file mẫu: Excel = bảng 4 cột (Tháng, Khu vực, Sản phẩm, Doanh số) 20 dòng; Word = báo cáo 6 đoạn (đoạn 1 "
    "tiêu đề, 2 và 4 là đề mục); PowerPoint = 3 slide (slide 1 tiêu đề; slide 2–3 có tiêu đề và nội dung gạch đầu "
    "dòng). 'selection' là vùng cần chọn trước. Bỏ qua việc cần file khác, mạng, tài khoản, macro, in ấn. "
    "(2) 'notes': kiến thức hữu ích ngắn (mẹo, phím tắt, khi nào dùng), tự diễn đạt lại, không chép nguyên văn. "
    "Không có gì đáng học thì trả danh sách rỗng. Chỉ trả JSON."
)


@lru_cache(maxsize=None)
def ribbon(app: str) -> dict[str, list[dict]]:
    name = "ribbon_dump.json" if app == "excel" else f"ribbon_dump_{app}.json"
    path = DUMPS / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def slug(app: str, title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", fold(title))[:40].strip("_") or "task"
    return f"learn_{app[:3]}_{base}_{hashlib.sha1(title.encode()).hexdigest()[:4]}"


def build_card(t: XTask, source: str, where: str) -> tuple[dict | None, str]:
    """Return (card, "") or (None, reason). Names are replaced by the exact UIA names from the ribbon dump."""
    dump = ribbon(t.app)
    if not dump:
        return None, f"chưa có dump ribbon cho {t.app}"
    aliases = load_aliases()
    if not t.steps or t.steps[0].intent != "select_ribbon_tab":
        return None, "bước đầu không phải chọn tab ribbon"
    steps, tab, in_menu, unverified = [], None, False, False
    for i, s in enumerate(t.steps, start=1):
        wanted = expand_names([n for n in s.names if n], aliases)
        if s.intent == "select_ribbon_tab":
            best = max(dump, key=lambda tab_name: name_score(tab_name, wanted), default=None)
            if best is None or name_score(best, wanted) < 85:
                return None, f"không có tab ribbon '{s.names[0] if s.names else '?'}'"
            tab, in_menu = best, False
            steps.append({"id": i, "intent": "select_ribbon_tab",
                          "target": {"names": [best] + [n for n in s.names[1:] if n != best], "control_type": "TabItem"},
                          "expected": {"type": "tab_selected"}})
            continue
        rows = dump.get(tab, [])
        hit = max(rows, key=lambda r: name_score(r["name"], wanted), default=None)
        score = name_score(hit["name"], wanted) if hit else 0
        target: dict
        if hit and score >= 85 and not in_menu:
            ct = hit["ct"]
            target = {"names": [hit["name"]] + [n for n in s.names[1:] if n != hit["name"]], "control_type": ct}
            if hit.get("aid"):
                target["automation_id"] = hit["aid"]
            if s.intent == "expand" and ct == "SplitButton":
                target["control_type"] = "SplitButton|MenuItem"
        elif in_menu or s.intent in ("select_item", "set_value") or (s.names and s.names[0].strip().upper() == "OK"):
            # inside a menu, gallery or dialog: not in the ribbon dump; the demonstration decides
            target = {"names": [n for n in s.names if n], "control_type": "ListItem|MenuItem|Button"
                      if s.intent in ("select_item", "invoke") else s.control_type}
            unverified = True
        else:
            return None, f"không thấy nút '{s.names[0] if s.names else '?'}' trên tab {tab}"
        step = {"id": i, "intent": s.intent, "target": target}
        if s.value is not None and s.intent == "set_value":
            step["value"] = s.value
        nxt = t.steps[i] if i < len(t.steps) else None
        if s.intent == "expand":
            step["expected"] = {"type": "expanded"}
            in_menu = True
        elif s.intent == "invoke" and nxt is not None and nxt.names and nxt.names[0].strip().upper() == "OK":
            step["expected"] = {"type": "dialog_opened"}
            in_menu = True
        elif s.names and s.names[0].strip().upper() == "OK":
            step["expected"] = {"type": "dialog_closed"}
            in_menu = False
        else:
            step["expected"] = {"type": "none"}
            if s.intent in ("select_item", "invoke", "toggle"):
                in_menu = False
        if i == len(t.steps):
            step["capture_result"] = True
        steps.append(step)
    card = {"id": slug(t.app, t.title), "title": t.title.strip(),
            "keywords": sorted({k.strip() for k in t.keywords if 2 < len(k.strip()) < 80})[:10],
            "fixture_id": FIXTURE[t.app], "steps": steps,
            **({"example": t.example.strip()[:400]} if t.example.strip() else {}),
            "learned": {"source": source[:160], "where": where[:200], "names_checked": not unverified}}
    ref = SELECT.get(t.app, {}).get(t.selection)
    if ref:
        card["preconditions"] = [{"type": "select_range", "ref": ref}]
    return card, ""


def signature(card: dict) -> tuple:
    """Same button sequence = same task, whatever the title."""
    return tuple((s["intent"], fold((s.get("target") or {}).get("names", [""])[0])) for s in card["steps"])
