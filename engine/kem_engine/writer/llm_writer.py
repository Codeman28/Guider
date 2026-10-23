"""Writer — LLM call #2 (SPEC §6.10). One call for the whole tutorial.

Guards (ADR-7): bold labels must be real UIA names from the Trace; tips may only mention a shortcut that
UIA reported; step count and order come from the Trace. One repair attempt; if labels are still wrong
they are replaced by code. Any failure (no model, budget, invalid output) falls back to the template.
"""
from __future__ import annotations

import re
from typing import Optional

import structlog
from pydantic import BaseModel

from ..llm.client import LLMClient
from ..llm.providers.base import LLMError
from ..models import Trace, Tutorial
from . import template

log = structlog.get_logger()

SYSTEM = (
    "Bạn viết hướng dẫn sử dụng Excel bằng tiếng Việt tự nhiên cho người dùng phổ thông, giống các bài "
    "hướng dẫn quen thuộc. Mỗi bước trong 'steps' đầu vào thành đúng một bước đầu ra, cùng thứ tự, cùng id. "
    "Câu ngắn, mỗi bước một hành động. Nhãn nút in đậm bằng **...** và phải giữ NGUYÊN chuỗi element_name. "
    "Không thêm bước, không bịa phím tắt (chỉ nhắc access_key nếu có), không nói 'theo hình'. "
    "Bước có verified=false: nói rõ Guider chưa làm mẫu được bước này trên máy bạn. Chỉ trả JSON."
)


class WStep(BaseModel):
    id: int
    heading: str
    body: str
    tip: Optional[str] = None


class WOut(BaseModel):
    title: str
    intro: str
    steps: list[WStep]
    outro: str


def _names(trace: Trace) -> set[str]:
    return {template.clean(s.element_name or "") for s in trace.steps}


def problems(out: WOut, trace: Trace) -> list[str]:
    probs = []
    if [s.id for s in out.steps] != [s.id for s in trace.steps]:
        probs.append(f"steps phải có đúng các id {[s.id for s in trace.steps]} theo thứ tự")
    names = _names(trace)
    for s in out.steps:
        for part in (s.heading, s.body, s.tip or ""):
            bad = [b for b in template.bold_labels(part) if b not in names]
            if bad:
                probs.append(f"bước {s.id}: nhãn in đậm không có thật: {bad}")
    return probs


def _fix_labels(text: str, name: str) -> str:
    """Bold labels must be the exact UIA name; quoted mentions of it ('Italic', “Italic”) become bold."""
    if name:
        for q1, q2 in (("'", "'"), ('"', '"'), ("“", "”"), ("‘", "’")):
            text = text.replace(f"{q1}{name}{q2}", f"**{name}**")
    return re.sub(r"\*\*(.+?)\*\*", lambda m: m.group(0) if m.group(1) == name else f"**{name}**", text)


def write(trace: Trace, title: str, tutorial_id: str, status: str, llm: LLMClient | None) -> tuple[Tutorial, str]:
    """Returns (tutorial, source) where source is 'llm' or 'template'."""
    base = template.write(trace, title, tutorial_id, status)
    if llm is None or not trace.steps or llm.budget.remaining <= 0:
        return base, "template"
    payload = {
        "title": title,
        "env": {"app": trace.env.app, "ui_lang": trace.env.ui_lang, "office_build": trace.env.office_build},
        "steps": [{"id": s.id, "intent": s.intent, "element_name": template.clean(s.element_name or ""),
                   "control_type": s.control_type, "access_key": s.access_key, "value": s.value,
                   "verified": s.verified, "inserted_reason": s.inserted_reason} for s in trace.steps],
    }
    try:
        out = llm.complete("writer", SYSTEM, payload, WOut, max_repairs=1, reserve=2.0)
    except LLMError as e:
        log.warning("writer.fallback_template", error=str(e))
        return base, "template"
    found = problems(out, trace)
    if found:
        log.info("writer.fixing", problems=found)  # labels are fixed by code below; wrong ids → template
    if [s.id for s in out.steps] != [s.id for s in trace.steps]:
        return base, "template"
    # Headings stay deterministic (template, exact UIA label). The model contributes the body text,
    # kept only if it names the element in bold; otherwise the template body is used.
    steps = []
    for ws, ts, bs in zip(out.steps, trace.steps, base.steps):
        name = template.clean(ts.element_name or "")
        body = _fix_labels(ws.body, name)
        if not ts.verified or f"**{name}**" not in body:
            body = bs.body
        tip = ws.tip if (ws.tip and ts.access_key and ts.access_key in ws.tip) else bs.tip
        steps.append(bs.model_copy(update={"body": body, "tip": tip}))
    outro = out.outro if status == "ok" and out.outro else base.outro
    tut = base.model_copy(update={"outro": outro, "steps": steps})
    if template.validate_labels(tut, trace):  # should be impossible after _fix_labels
        return base, "template"
    return tut, "llm"
