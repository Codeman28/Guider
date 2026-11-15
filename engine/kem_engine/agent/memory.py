"""What the agent keeps between runs (ADR-0008): lessons from its own attempts, and the goals it has not managed yet.

Both live next to the learned cards in %LOCALAPPDATA%\\Kem\\knowledge, so they survive reinstalls and stay on this
machine. A lesson is one short sentence of Office know-how drawn from a run ("the Font dialog colour picker opens
on a click; choose Red in its list"); the next runs on a similar goal read them before choosing an action. A goal
the agent could not reach goes to the practice queue, and Guider tries it again later, with what it learned.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import structlog

log = structlog.get_logger()

MAX_LESSONS = 300  # per app; the oldest go first
MAX_TRIES = 6  # practice rounds per goal before Guider stops retrying it on its own
_lock = threading.Lock()


def _root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Kem" / "knowledge"


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------------------------- lessons
def lessons_path(app: str) -> Path:
    return _root() / f"{app}.lessons.json"


def add_lessons(app: str, goal: str, lessons: list[str], ok: bool) -> None:
    lessons = [x.strip() for x in lessons if x and x.strip()][:4]
    if not lessons:
        return
    with _lock:
        path = lessons_path(app)
        rows = _read(path, [])
        known = {r["text"] for r in rows}
        now = time.strftime("%d/%m/%Y")
        rows += [{"goal": goal[:160], "text": t[:300], "ok": ok, "when": now} for t in lessons if t not in known]
        _write(path, rows[-MAX_LESSONS:])
    log.info("agent.lessons_saved", app=app, n=len(lessons), ok=ok)


def lessons_for(app: str, goal: str, k: int = 8) -> list[str]:
    """Lessons from runs on a similar goal first, then the most recent ones (general Office know-how)."""
    from rapidfuzz import fuzz

    from ..intent.knowledge import fold
    rows = _read(lessons_path(app), [])
    if not rows:
        return []
    g = fold(goal)
    scored = sorted(enumerate(rows), key=lambda ir: (fuzz.token_set_ratio(g, fold(ir[1]["goal"])) >= 60, ir[0]),
                    reverse=True)
    out = []
    for _, r in scored:
        if r["text"] not in out:
            out.append(r["text"])
        if len(out) >= k:
            break
    return out


REFLECT = ("Bạn vừa thử tự làm một việc trong Microsoft Office. Từ mục tiêu, các bước đã làm (kèm kết quả) và kết "
           "luận kiểm tra, hãy rút ra 1-3 bài học NGẮN (mỗi bài một câu tiếng Việt) để lần sau làm đúng ngay: cách "
           "nào hiệu quả, cách nào không dùng được và nên làm gì thay thế. Bài học phải dùng lại được cho việc "
           "tương tự (tên nút, menu, hộp thoại, phím tắt), không nhắc ô hay số liệu riêng của file mẫu. "
           "Không khuyên dùng chuỗi phím Alt (Alt+N+V…): Guider không dùng được chúng. Lỗi kỹ thuật của chính Guider "
           "(ứng dụng bận, hết thời gian, không đọc được) không phải bài học về Office, đừng ghi. "
           "Trả lời JSON {\"lessons\": [\"...\"]}.")


def reflect(goal: str, history: list[dict], verdict_reason: str, achieved: bool) -> list[str]:
    """One short text call: what this attempt teaches. Falls back to the failed actions themselves."""
    steps = "\n".join(f"{i}. {h['what']} → {h['result']}" for i, h in enumerate(history, 1)) or "(không có bước nào)"
    text = (f"Mục tiêu: {goal}\nCác bước:\n{steps}\nKết luận kiểm tra: "
            f"{'ĐẠT' if achieved else 'CHƯA ĐẠT'} — {verdict_reason}")
    try:
        from ..vision.exercise import _gemini
        raw = _gemini([{"role": "system", "content": REFLECT}, {"role": "user", "content": text}], 30, 600)
        data = json.loads(raw or "{}")
        lessons = [str(x) for x in data.get("lessons", []) if str(x).strip()]
        if lessons:
            return lessons[:3]
    except Exception as e:
        log.info("agent.reflect_failed", error=repr(e))
    bad = [f"'{h['what']}' không dùng được ({h['result'][:80]})" for h in history
           if not h["result"].startswith("đã làm")]
    return bad[:2]


# ------------------------------------------------------------------------------------------ practice queue
def practice_path() -> Path:
    return _root() / "practice.json"


def queue_goal(app: str, goal: str, why: str) -> None:
    with _lock:
        rows = _read(practice_path(), [])
        row = next((r for r in rows if r["goal"] == goal and r["app"] == app), None)
        if row is None:
            row = {"app": app, "goal": goal, "tries": 0, "solved": False}
            rows.append(row)
        row.update(why=why[:300], last=time.strftime("%d/%m/%Y %H:%M"), solved=False)
        _write(practice_path(), rows)
    log.info("agent.queued_for_practice", app=app, goal=goal[:80])


def mark(app: str, goal: str, solved: bool, why: str = "") -> None:
    """After a practice (or a normal) run on a queued goal: solved leaves the queue, else one more try counted."""
    with _lock:
        rows = _read(practice_path(), [])
        row = next((r for r in rows if r["goal"] == goal and r["app"] == app), None)
        if row is None:
            return
        row["tries"] = row.get("tries", 0) + 1
        row["solved"] = solved
        row["last"] = time.strftime("%d/%m/%Y %H:%M")
        if why:
            row["why"] = why[:300]
        _write(practice_path(), rows)


def pending() -> list[dict]:
    """Goals still to practise, the least tried first."""
    rows = [r for r in _read(practice_path(), []) if not r.get("solved") and r.get("tries", 0) < MAX_TRIES]
    return sorted(rows, key=lambda r: r.get("tries", 0))


def queue() -> list[dict]:
    return _read(practice_path(), [])
