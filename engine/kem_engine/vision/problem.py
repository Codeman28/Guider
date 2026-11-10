"""Read a screenshot or photo of the user's Office problem (ADR-0005).

When a Gemini key is saved, Gemini reads the picture (a few seconds): setting `vision_cloud` is ON by default and the user can turn it off in Settings; the chat says, before sending, that the
picture goes to Gemini. Without a key, with the setting off, or when Gemini fails, everything runs on this
machine: a local vision model through Ollama (gemma3:4b, ~100 s per picture on a laptop CPU), Windows OCR as
the last fallback. The task question that comes out of the picture (the
same kind of text the user would type) goes on to the Planner as before.

Pipeline: prepare (copy, shrink) → OCR → vision model (app, visible text, problem, task, visible table)
→ shortlist cards → the model picks one (or none) → a sample file built from what the picture shows.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import structlog
from pydantic import BaseModel, Field, ValidationError
from rapidfuzz import fuzz

from ..intent.knowledge import KnowledgePack, fold

log = structlog.get_logger()

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_SIDE = 1600  # the vision model sees at most this many pixels on the long side
OCR_SCRIPT = Path(__file__).with_name("ocr.ps1")
if getattr(sys, "frozen", False):  # PyInstaller sidecar: data files sit under _MEIPASS
    OCR_SCRIPT = Path(getattr(sys, "_MEIPASS", ".")) / "kem_engine" / "vision" / "ocr.ps1"
CONFIG = Path(__file__).resolve().parents[2] / "config" / "llm.toml"
MAX_ROWS, MAX_COLS = 30, 12

# Error values seen on a sheet → a formula that really gives that error, so the sample shows the same problem
ERROR_FORMULAS = {"#N/A": "=NA()", "#DIV/0!": "=1/0", "#VALUE!": '="a"+1', "#REF!": "=#REF!",
                  "#NAME?": "=KHONGCOHAM()", "#NUM!": "=SQRT(-1)", "#NULL!": "=A1 A2"}


class ProblemError(Exception):
    """Shown to the user as is (Vietnamese)."""


@dataclass
class VisionConf:
    base_url: str = "http://127.0.0.1:11434"
    model: str = "gemma3:4b"
    timeout_s: float = 75.0
    keep_alive: str = "30m"
    max_side: int = MAX_SIDE

    @classmethod
    def load(cls, path: Path | None = None) -> "VisionConf":
        try:
            raw = tomllib.loads((path or CONFIG).read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return cls()
        v, o = raw.get("vision", {}), raw.get("ollama", {})
        return cls(base_url=v.get("base_url", o.get("base_url", cls.base_url)), model=v.get("model", cls.model),
                   timeout_s=float(v.get("timeout_s", cls.timeout_s)), keep_alive=o.get("keep_alive", cls.keep_alive),
                   max_side=int(v.get("max_side", MAX_SIDE)))


class SeenTable(BaseModel):
    columns: list[str] = Field(default_factory=list, max_length=MAX_COLS)
    rows: list[list[str]] = Field(default_factory=list, max_length=MAX_ROWS)


class Seen(BaseModel):
    """What the vision model answers. Kept small: on CPU every output token costs (10/11/2026: a nested
    JSON table plus OCR hints took 158 s)."""
    app: Literal["excel", "word", "powerpoint", "other"]
    problem: str
    task: str
    visible_text: str = ""
    error_value: str = ""
    content: str = ""  # Excel: "a | b | c" per row, header first; Word/PowerPoint: one paragraph per line


class Diagnosis(BaseModel):
    app: Literal["excel", "word", "powerpoint", "other"]
    visible_text: str = ""
    problem: str
    task: str
    error_value: Optional[str] = None
    table: Optional[SeenTable] = None
    paragraphs: list[str] = Field(default_factory=list)

    @classmethod
    def from_seen(cls, s: Seen) -> "Diagnosis":
        lines = [ln.strip() for ln in s.content.splitlines() if ln.strip()]
        table, paras = None, []
        if s.app == "excel":
            grid = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines if "|" in ln]
            grid = [r for r in grid if any(r) and not all(set(c) <= set("-: ") for c in r)]  # drop |---| rules
            if len(grid) >= 2:
                width = min(MAX_COLS, max(len(r) for r in grid))
                table = SeenTable(columns=(grid[0] + [""] * width)[:width],
                                  rows=[(r + [""] * width)[:width] for r in grid[1:MAX_ROWS + 1]])
        else:
            paras = lines[:12]
        return cls(app=s.app, visible_text=s.visible_text[:400], problem=s.problem.strip(), task=s.task.strip(),
                   error_value=s.error_value.strip() or None, table=table, paragraphs=paras)


class Pick(BaseModel):
    choice: int = Field(description="số thứ tự của việc phù hợp nhất, 0 nếu không việc nào sửa được vấn đề")


@dataclass
class ProblemRead:
    image: Path  # the prepared copy (PNG) — shown in the tutorial, kept local
    ocr: list[str]
    diagnosis: Diagnosis
    card_id: str | None = None
    query: str = ""
    seconds: float = 0.0
    timings: dict = field(default_factory=dict)

    def summary(self) -> dict:
        d = self.diagnosis
        return {"summary": d.problem, "visible_text": d.visible_text, "task": d.task, "error_value": d.error_value,
                "card_id": self.card_id}


# ---------------------------------------------------------------- picture in

def is_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXT


def prepare(src: str | Path, work: Path, max_side: int = MAX_SIDE) -> Path:
    """Copy the user's picture into the work folder as PNG, shrunk to max_side. The original is never changed."""
    from PIL import Image, UnidentifiedImageError
    p = Path(src)
    if not p.is_file() or not is_image(p):
        raise ProblemError("Chỉ nhận ảnh PNG, JPG, BMP, GIF hoặc WEBP có trên máy.")
    if p.stat().st_size > MAX_IMAGE_BYTES:
        raise ProblemError("Ảnh quá lớn (tối đa 25 MB).")
    try:
        with Image.open(p) as im:
            im = im.convert("RGB")
            if max(im.size) > max_side:
                im.thumbnail((max_side, max_side), Image.LANCZOS)
            work.mkdir(parents=True, exist_ok=True)
            out = work / "problem.png"
            im.save(out, "PNG")
    except (UnidentifiedImageError, OSError) as e:
        raise ProblemError("Không mở được ảnh này. Hãy chụp lại hoặc lưu thành PNG.") from e
    return out


def save_pasted(data_b64: str, work: Path) -> Path:
    """An image pasted into the chat (clipboard) arrives as base64; write it so prepare() can read it."""
    raw = base64.b64decode(data_b64.split(",", 1)[-1], validate=False)
    if len(raw) > MAX_IMAGE_BYTES:
        raise ProblemError("Ảnh quá lớn (tối đa 25 MB).")
    work.mkdir(parents=True, exist_ok=True)
    out = work / "pasted.png"
    out.write_bytes(raw)
    return out


def ocr(image: Path, timeout: float = 25.0) -> list[str]:
    """Windows' own OCR (no download, no network). Small text reads better at 2x; empty list if unavailable."""
    from PIL import Image
    src = image
    try:
        with Image.open(image) as im:
            if max(im.size) < 1400:
                src = image.with_name("ocr_x2.png")
                im.resize((im.width * 2, im.height * 2), Image.LANCZOS).save(src)
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                              "-File", str(OCR_SCRIPT), str(src)], capture_output=True, timeout=timeout,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode != 0:
            log.info("problem.ocr_failed", err=out.stderr.decode("utf-8", "ignore")[:200])
            return []
        data = json.loads(out.stdout.decode("utf-8", "ignore") or "{}")
        return [ln["text"] for ln in data.get("lines", []) if ln.get("text", "").strip()]
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        log.info("problem.ocr_unavailable", error=repr(e))
        return []
    finally:
        if src != image:
            src.unlink(missing_ok=True)


# ---------------------------------------------------------------- local vision model

def _ollama(conf: VisionConf, messages: list[dict], schema: dict, timeout: float, max_tokens: int = 900) -> str:
    body = {"model": conf.model, "stream": False, "format": schema, "keep_alive": conf.keep_alive,
            "options": {"temperature": 0.1, "num_predict": max_tokens}, "messages": messages}
    req = urllib.request.Request(conf.base_url.rstrip("/") + "/api/chat", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())["message"]["content"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ProblemError(f"Máy chưa có model đọc ảnh {conf.model}. Hãy mô tả vấn đề bằng chữ.") from e
        raise ProblemError("Model đọc ảnh trên máy báo lỗi. Hãy thử lại hoặc mô tả bằng chữ.") from e
    except (TimeoutError, urllib.error.URLError, ConnectionError) as e:
        if isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError):
            raise ProblemError("Đọc ảnh quá lâu. Hãy cắt ảnh gọn vào chỗ lỗi rồi thử lại.") from e
        raise ProblemError("Chưa chạy được model đọc ảnh trên máy (Ollama chưa mở).") from e


def warm_up(conf: VisionConf | None = None) -> None:
    """Load the vision model while the user is still typing (a cold load costs ~60-80 s on CPU)."""
    conf = conf or VisionConf.load()
    try:
        body = {"model": conf.model, "messages": [], "stream": False, "keep_alive": conf.keep_alive}
        req = urllib.request.Request(conf.base_url.rstrip("/") + "/api/chat", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=180).read()
    except Exception as e:  # best effort
        log.info("problem.warm_up_failed", error=repr(e))


SYSTEM = (
    "Bạn là Guider, trợ lý hướng dẫn Microsoft Office (Excel, Word, PowerPoint). Người dùng gửi ảnh chụp màn hình "
    "vấn đề của họ. Đọc kỹ chữ trên ảnh: thanh công thức, giá trị lỗi (#N/A, #DIV/0!, #VALUE!, #REF!, #NAME?), "
    "hộp thoại thông báo, tên nút. Không bịa chữ không có trên ảnh. Trả lời tiếng Việt.\n"
    "- app: ứng dụng trên ảnh (other nếu không phải Office).\n"
    "- problem: vấn đề cụ thể và nguyên nhân có khả năng nhất.\n"
    "- task: MỘT việc làm trong Office giúp sửa vấn đề, viết như câu hỏi 'Cách ...' (vd 'Cách dùng IFERROR để ẩn "
    "lỗi #N/A', 'Cách cố định dòng tiêu đề khi cuộn').\n"
    "- visible_text: công thức hoặc thông báo lỗi đọc được, ngắn gọn.\n"
    "- error_value: giá trị lỗi Excel nếu có (vd #N/A), không có thì để trống.\n"
    "- content: Excel: chép bảng nhìn thấy, mỗi hàng một dòng, các ô cách nhau bằng ' | ', hàng tiêu đề trước, "
    "tối đa 10 hàng; không chép chữ cột A B C hay số thứ tự dòng. Word/PowerPoint: tối đa 6 đoạn chữ, mỗi đoạn "
    "một dòng.")


def cloud_enabled() -> bool:
    """A Gemini key saved with DPAPI, and the user has not turned "Đọc ảnh bằng Gemini" off (on by default)."""
    from ..llm.config import settings_path
    from ..llm.secrets import has_key
    try:
        on = json.loads(settings_path().read_text(encoding="utf-8")).get("vision_cloud", True) is not False
    except (OSError, ValueError):
        on = True
    return on and has_key("gemini")


def look_cloud(image: Path, question: str, timeout: float) -> Diagnosis:
    """Gemini reads the picture (2-5 s). Only called when cloud_enabled(); errors fall back to the local model."""
    import openai

    from ..llm.config import LLMConfig
    conf = LLMConfig.load().providers.get("gemini")
    if conf is None or not conf.api_key():
        raise ProblemError("Chưa có API key Gemini.")
    client = openai.OpenAI(base_url=conf.base_url, api_key=conf.api_key(), timeout=timeout, max_retries=0)
    url = "data:image/png;base64," + base64.b64encode(image.read_bytes()).decode()
    user = f"Câu hỏi của người dùng: {question.strip() or '(không có, hãy tự nhận ra vấn đề trên ảnh)'}"
    try:
        r = client.chat.completions.create(
            model=conf.models[0], temperature=0.1, max_tokens=1200, timeout=timeout,
            **({"reasoning_effort": conf.reasoning_effort} if conf.reasoning_effort else {}),
            messages=[{"role": "system", "content": SYSTEM + " Trả về JSON: " + json.dumps(Seen.model_json_schema(),
                                                                                    ensure_ascii=False)},
                      {"role": "user", "content": [{"type": "text", "text": user},
                                                   {"type": "image_url", "image_url": {"url": url}}]}],
            response_format={"type": "json_object"})
        return Diagnosis.from_seen(Seen.model_validate_json(r.choices[0].message.content or ""))
    except (openai.APIError, ValidationError) as e:
        raise ProblemError(f"Gemini không đọc được ảnh: {type(e).__name__}") from e


def look(image: Path, question: str, ocr_lines: list[str], conf: VisionConf, timeout: float) -> Diagnosis:
    """ocr_lines are not given to the model: Windows OCR drops Vietnamese marks and error values and the model
    copied its mistakes (10/11/2026). They stay in the read result as a record."""
    img = base64.b64encode(image.read_bytes()).decode()
    user = f"Câu hỏi của người dùng: {question.strip() or '(không có, hãy tự nhận ra vấn đề trên ảnh)'}"
    schema = Seen.model_json_schema()
    last: Exception | None = None
    for _ in range(2):
        raw = _ollama(conf, [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": user, "images": [img]}], schema, timeout, max_tokens=500)
        try:
            return Diagnosis.from_seen(Seen.model_validate_json(raw))
        except ValidationError as e:
            last = e
            log.info("problem.diagnosis_invalid", error=str(e)[:200])
    raise ProblemError("Guider chưa hiểu được ảnh này. Hãy mô tả vấn đề bằng chữ.") from last


APP_WORDS = {"excel": "excel", "word": "word", "powerpoint": "powerpoint"}


def from_ocr(lines: list[str], question: str) -> Diagnosis | None:
    """Without a vision model: the app from the window title, an error value if one is readable."""
    text = " ".join(lines)
    low = text.lower()
    app = next((a for w, a in APP_WORDS.items() if f"- {w}" in low or low.endswith(w)), None)
    from ..intent.router import route
    if app is None and question.strip():
        app = route(question, None).app
    if app is None:
        return None
    err = next((e for e in ERROR_FORMULAS if e.replace("0", "O") in text.upper() or e in text.upper()), None)
    task = question.strip() or (f"Cách sửa lỗi {err} trong Excel" if err else "")
    if not task:
        return None
    return Diagnosis(app=app, visible_text=" ".join(lines[:20])[:400], problem=(f"Ô báo lỗi {err}." if err else
                     "Guider chưa đọc được ảnh, chỉ dựa vào câu hỏi của bạn."), task=task, error_value=err)


# ---------------------------------------------------------------- task: a learned card, or a question for the Planner

def shortlist(pack: KnowledgePack, d: Diagnosis, question: str, k: int = 10) -> list:
    texts = [d.task, d.problem, question, d.visible_text]
    found: dict[str, float] = {}
    for t in texts:
        for s, c in pack.match(t or "", top_k=5):
            if s > 0:
                found[c.id] = max(found.get(c.id, 0), s)
    probe = fold(" ".join(t for t in texts[:2] if t))
    for c in pack.cards:
        s = max(fuzz.token_set_ratio(probe, fold(c.title)),
                max((fuzz.token_set_ratio(probe, fold(kw)) for kw in c.keywords), default=0)) * 0.9
        if s >= 55:
            found[c.id] = max(found.get(c.id, 0), s)
    ranked = sorted(found.items(), key=lambda kv: -kv[1])[:k]
    return [pack.by_id[cid] for cid, _ in ranked]


def _cloud_json(system: str, user: str, schema: dict, timeout: float) -> str:
    import openai

    from ..llm.config import LLMConfig
    conf = LLMConfig.load().providers.get("gemini")
    client = openai.OpenAI(base_url=conf.base_url, api_key=conf.api_key(), timeout=timeout, max_retries=0)
    r = client.chat.completions.create(
        model=conf.models[0], temperature=0.1, max_tokens=300, timeout=timeout,
        **({"reasoning_effort": conf.reasoning_effort} if conf.reasoning_effort else {}),
        messages=[{"role": "system", "content": system + " Trả về JSON: " + json.dumps(schema, ensure_ascii=False)},
                  {"role": "user", "content": user}], response_format={"type": "json_object"})
    return r.choices[0].message.content or ""


def pick_card(cards: list, d: Diagnosis, conf: VisionConf, timeout: float, cloud: bool = False) -> str | None:
    """A model chooses among learned tasks (text only, no picture); 0 → none fits. Local unless the user
    already chose Gemini for pictures."""
    if not cards:
        return None
    menu = "\n".join(f"{i}. {c.title}" for i, c in enumerate(cards, 1))
    user = (f"Vấn đề: {d.problem}\nViệc cần làm: {d.task}\nChữ trên ảnh: {d.visible_text}\n\n"
            f"Các bài Guider đã học:\n{menu}\n\nChọn bài giúp sửa đúng vấn đề này. 0 nếu không bài nào phù hợp.")
    try:
        if cloud:
            raw = _cloud_json("Bạn chọn bài hướng dẫn Office phù hợp.", user, Pick.model_json_schema(), timeout)
        else:
            raw = _ollama(conf, [{"role": "user", "content": user}], Pick.model_json_schema(), timeout, max_tokens=40)
        n = Pick.model_validate_json(raw).choice
    except Exception as e:  # a failed pick only means the Planner gets the task question instead
        log.info("problem.pick_failed", error=repr(e)[:200])
        return None
    return cards[n - 1].id if 1 <= n <= len(cards) else None


# ---------------------------------------------------------------- the sample file

def _cell(v: str):
    s = (v or "").strip()
    if s.upper() in ERROR_FORMULAS:
        return ERROR_FORMULAS[s.upper()]
    if s.startswith("="):  # a formula seen on the picture cannot be trusted to work here: keep it as text
        return "'" + s
    num = s.replace(" ", "").replace(",", "")
    if re.fullmatch(r"-?\d+(\.\d+)?", num) and not (len(num) > 1 and num.startswith("0") and "." not in num):
        return float(num) if "." in num else int(num)
    return s


def sample_fixture(d: Diagnosis) -> dict | None:
    """What the picture shows, as a fixture for the sandbox. None → the task's own sample is used."""
    if d.app == "excel" and d.table and d.table.columns and d.table.rows:
        cols = [c.strip() or f"Cột {i}" for i, c in enumerate(d.table.columns[:MAX_COLS], 1)]
        rows = [[_cell(v) for v in (r + [""] * len(cols))[:len(cols)]] for r in d.table.rows[:MAX_ROWS]]
        rows = [r for r in rows if any(v not in ("", None) for v in r)]
        if rows:
            return {"id": "problem_sample", "description": "Dựng lại từ ảnh người dùng gửi", "columns": cols, "rows": rows}
    if d.app == "word" and d.paragraphs:
        return {"id": "problem_sample", "paragraphs": [p for p in d.paragraphs if p.strip()][:12] or ["(trống)"]}
    if d.app == "powerpoint" and d.paragraphs:
        ps = [p for p in d.paragraphs if p.strip()][:12]
        return {"id": "problem_sample", "slides": [{"title": ps[0], "body": ps[1:6]}]} if ps else None
    return None


def needs_own_layout(card) -> bool:
    """Formula lessons type cell addresses that only make sense on their own sample table."""
    return any(s.get("intent") == "type_formula"
               or (s.get("intent") == "set_value" and str(s.get("value", "")).startswith("="))  # a rule's formula
               for s in card.raw.get("steps", []))


# ---------------------------------------------------------------- all together

def read(image_src: str | Path, question: str, pack_for, work: Path, conf: VisionConf | None = None,
         deadline: float | None = None) -> ProblemRead:
    """pack_for(app) → KnowledgePack. Raises ProblemError with a message for the user."""
    conf = conf or VisionConf.load()
    t0 = time.monotonic()
    deadline = deadline or t0 + 90
    img = prepare(image_src, work, conf.max_side)
    t_prep = time.monotonic()
    lines: list[str] = []
    t_ocr = time.monotonic()
    d = None
    reader = "local"
    if cloud_enabled():
        try:
            d, reader = look_cloud(img, question, 30), "gemini"
        except ProblemError as e:
            log.info("problem.cloud_failed", error=str(e))
    if d is None:
        left = max(30.0, min(conf.timeout_s, deadline - time.monotonic()))
        try:
            d = look(img, question, lines, conf, left)
        except ProblemError as e:  # no vision model (or too slow): Windows OCR still finds error values
            lines = ocr(img)
            d = from_ocr(lines, question)
            if d is None:
                raise
            reader = "ocr"
            log.info("problem.ocr_fallback", reason=str(e))
    t_look = time.monotonic()
    if d.app == "other":
        raise ProblemError("Ảnh này không giống Excel, Word hay PowerPoint. Guider chỉ hướng dẫn trong Office.")
    pack = pack_for(d.app)
    cards = shortlist(pack, d, question)
    card_id = None
    from ..planner.planner import card_is_clear
    direct = pack.match(d.task)
    # The task names a learned card plainly: no second model call. Learned keywords can be loose ("xóa dữ
    # liệu" on the delete-chart card, 10/11/2026), so the title must also read like the task.
    if card_is_clear(direct) and fuzz.token_set_ratio(fold(d.task), fold(direct[0][1].title)) >= 70:
        card_id = direct[0][1].id
    elif cards:
        left = max(10.0, min(40.0, deadline - time.monotonic()))
        card_id = pick_card(cards, d, conf, left, cloud=reader == "gemini")
    t_pick = time.monotonic()
    q = pack.by_id[card_id].title if card_id else d.task
    res = ProblemRead(img, lines, d, card_id, q, time.monotonic() - t0,
                      {"reader": reader, "prepare": round(t_prep - t0, 2), "ocr": round(t_ocr - t_prep, 2),
                       "look": round(t_look - t_ocr, 2), "pick": round(t_pick - t_look, 2)})
    log.info("problem.read", app=d.app, card=card_id, task=d.task, seconds=round(res.seconds, 1), **res.timings)
    return res


# ---------------------------------------------------------------- the user's own Office window

OFFICE_FRAMES = {"XLMAIN": "excel", "OpusApp": "word", "PPTFrameClass": "powerpoint"}


def office_windows() -> list[dict]:
    """The user's open Office windows, front-most first (never Guider's own sandbox: it is not running now)."""
    from ..env import win32
    out = []
    for h in win32.top_level_windows():
        app = OFFICE_FRAMES.get(win32.class_name(h))
        if app and not win32.user32.IsIconic(h):
            out.append({"hwnd": int(h), "app": app, "title": win32.window_text(h)[:120]})
    return out


def capture_office(work: Path, hwnd: int | None = None) -> tuple[Path, dict]:
    """Screenshot of one of the user's Office windows (PrintWindow: it works under the Guider window too).
    Only a picture is taken — nothing is clicked or typed in the user's window. The click on
    "Chụp cửa sổ Office" is the user's permission; the picture stays on this machine."""
    from ..capture.printwindow import capture_window
    wins = office_windows()
    if hwnd is not None:
        wins = [w for w in wins if w["hwnd"] == hwnd]
    if not wins:
        raise ProblemError("Không thấy cửa sổ Excel, Word hay PowerPoint nào đang mở (hoặc đang thu nhỏ).")
    w = wins[0]
    try:
        img, _ = capture_window(w["hwnd"])
    except RuntimeError as e:
        raise ProblemError("Không chụp được cửa sổ đó. Hãy mở nó lên (không thu nhỏ) rồi thử lại.") from e
    work.mkdir(parents=True, exist_ok=True)
    out = work / "office_window.png"
    img.save(out, "PNG")
    return out, w
