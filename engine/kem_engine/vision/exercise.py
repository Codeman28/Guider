"""Exercise mode, "Giải bài tập" (ADR-0006): a picture of an Excel exercise → the same table rebuilt in a sandbox
workbook → a solution written for THAT table (formulas on the user's own columns), checked in a hidden Excel
→ demonstrated on the rebuilt table → tutorial. The "Hướng dẫn" mode stays for "how do I do X" questions,
demonstrated on Guider's own sample files.

Reading the picture and writing the solution use Gemini when the user has a key and has not turned picture
reading off (problem.cloud_enabled); otherwise the local models (gemma3:4b for the picture).
"""
from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import structlog
from pydantic import BaseModel, Field, ValidationError

from ..models import Expected, Plan, Step, Target
from . import problem as vp

log = structlog.get_logger()

MAX_ROWS, MAX_COLS = 40, 15
LETTER_HEAD = re.compile(r"^\s*([A-Z]{1,2})\s*[\(\[:\-–]\s*(.*?)\s*[\)\]]?\s*$")  # "B (Mã NV)" → "Mã NV"


class ExerciseError(Exception):
    """Shown to the user as is (Vietnamese)."""


# ---------------------------------------------------------------- reading the picture

class SeenExercise(BaseModel):
    app: str = "excel"
    content: str = ""  # the table, one row per line, cells separated by " | ", header first
    tasks: list[str] = Field(default_factory=list)  # the exercise's questions, as written on the picture
    notes: str = ""  # anything that changes how to read the table (units, a total row…)


READ_SYSTEM = (
    "Bạn đọc ảnh một bài tập Excel của học sinh/người đi làm. Chép lại ĐÚNG bảng trên ảnh để dựng lại file Excel.\n"
    "- content: mỗi hàng một dòng, các ô cách nhau bằng ' | ', hàng tiêu đề trước; chép đủ mọi hàng và MỌI cột "
    "(kể cả cột STT, cột trống có tiêu đề), giữ đúng thứ tự cột như trên ảnh "
    "(tối đa 40 hàng, 15 cột), giữ nguyên chữ, dấu tiếng Việt, số (không thêm dấu phân cách hàng nghìn).\n"
    "- Nếu ảnh có cột ghi số hàng (vd 'Cột / Hàng' với 2, 3, 4…) thì bỏ cột đó; nếu tiêu đề có chữ cột như "
    "'B (Mã NV)' thì chỉ ghi 'Mã NV'. Ô trống ghi rỗng.\n"
    "- tasks: các yêu cầu/câu hỏi của bài tập viết trên ảnh (vd 'Tính lương = Lương CB/26*Ngày công'), giữ "
    "nguyên ý; không có thì để danh sách rỗng.\n"
    "- app: excel nếu là bảng tính; word/powerpoint/other nếu không phải.")


GEMINI_MODELS = ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash")  # as in training/llm.py
_notify = None  # set by read_and_solve: tells the app what is happening while the user waits


def _say(msg: str) -> None:
    if _notify is not None:
        try:
            _notify(msg)
        except Exception:
            pass


def _gemini(messages: list[dict], timeout: float, max_tokens: int) -> str | None:
    """Gemini, retried and rotated across models when one is busy (HTTP 503/429 seen 11/11/2026). None when no
    Gemini model answered, so the caller falls back to the local model."""
    import openai

    from ..llm.config import LLMConfig
    conf = LLMConfig.load().providers.get("gemini")
    if conf is None or not conf.api_key():
        return None
    client = openai.OpenAI(base_url=conf.base_url, api_key=conf.api_key(), timeout=timeout, max_retries=0)
    models = list(dict.fromkeys(list(conf.models[:1]) + list(GEMINI_MODELS)))
    for n, model in enumerate(models):
        for attempt in range(2):
            try:
                r = client.chat.completions.create(
                    model=model, temperature=0.1, max_tokens=max_tokens, timeout=timeout, messages=messages,
                    **({"reasoning_effort": conf.reasoning_effort} if conf.reasoning_effort else {}),
                    response_format={"type": "json_object"})
                text = r.choices[0].message.content or ""
                if text.strip():
                    return text
            except (openai.RateLimitError, openai.InternalServerError, openai.APITimeoutError,
                    openai.APIConnectionError) as e:
                log.info("exercise.gemini_busy", model=model, attempt=attempt, error=repr(e)[:160])
                if n == 0 and attempt == 0:
                    _say("Gemini đang bận, Guider thử lại…")
                time.sleep(1.5 * (attempt + 1))
            except openai.APIError as e:  # model not available for this key, bad request: next model
                log.info("exercise.gemini_failed", model=model, error=repr(e)[:160])
                break
    return None


def _shape(schema: dict) -> str:
    """A one-line example of the wanted JSON, from the schema's top-level fields."""
    props = schema.get("properties", {})
    parts = []
    for k, v in props.items():
        t = v.get("type")
        parts.append(f'"{k}": ' + ("[...]" if t == "array" else "0" if t in ("integer", "number") else '"..."'))
    return "{" + ", ".join(parts) + "}"


def parse_seen(raw: str) -> "SeenExercise":
    """Tolerant read of the model's answer: the table may sit under an echoed schema or another wrapper."""
    try:
        seen = SeenExercise.model_validate_json(raw)
        if "|" in seen.content:
            return seen
    except ValidationError:
        pass
    data = json.loads(raw)
    found: dict = {}

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "content" and isinstance(v, str) and "|" in v and "content" not in found:
                    found["content"] = v
                elif k == "tasks" and isinstance(v, list) and all(isinstance(x, str) for x in v):
                    found.setdefault("tasks", v)
                elif k == "app" and isinstance(v, str) and v in ("excel", "word", "powerpoint", "other"):
                    found.setdefault("app", v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(data)
    return SeenExercise(**found)


def _vision(image: Path, system: str, user: str, schema: dict, timeout: float, max_tokens: int = 12000) -> str:
    """Gemini when allowed (a few seconds), else the local vision model (slow on CPU)."""
    if vp.cloud_enabled():
        url = "data:image/png;base64," + base64.b64encode(image.read_bytes()).decode()
        text = _gemini([{"role": "system", "content": system + " Trả về đúng một object JSON dạng " + _shape(schema)},
                        {"role": "user", "content": [{"type": "text", "text": user},
                                                     {"type": "image_url", "image_url": {"url": url}}]}],
                       timeout, max_tokens)
        if text is not None:
            return text
        _say("Gemini quá tải, Guider đọc ảnh bằng model trên máy (có thể mất 1–2 phút)…")
    conf = vp.VisionConf.load()
    img = base64.b64encode(image.read_bytes()).decode()
    return vp._ollama(conf, [{"role": "system", "content": system},
                             {"role": "user", "content": user, "images": [img]}], schema,
                      max(timeout, conf.timeout_s), max_tokens=max_tokens)


def _text_json(system: str, user: str, schema: dict, timeout: float, max_tokens: int = 8000) -> str:
    """Writing the solution: text only (the table as rebuilt, the tasks). Gemini when allowed, else local."""
    if vp.cloud_enabled():
        text = _gemini([{"role": "system", "content": system + " Trả về JSON: " + json.dumps(schema, ensure_ascii=False)},
                        {"role": "user", "content": user}], timeout, max_tokens)
        if text is not None:
            return text
        _say("Gemini quá tải, Guider viết lời giải bằng model trên máy (có thể mất 1–2 phút)…")
    conf = vp.VisionConf.load()
    return vp._ollama(conf, [{"role": "system", "content": system}, {"role": "user", "content": user}], schema,
                      max(timeout, conf.timeout_s), max_tokens=max_tokens)


def _clean_header(h: str) -> str:
    m = LETTER_HEAD.match(h or "")
    return (m.group(2) if m and m.group(2) else (h or "")).strip()


def table_fixture(content: str) -> dict | None:
    """The table as a sandbox fixture: header in row 1, data from row 2, column A first."""
    lines = [ln.strip() for ln in content.splitlines() if "|" in ln]
    grid = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]
    grid = [r for r in grid if not (any(r) and all(set(c) <= set("-: ") for c in r))]  # drop |---| rules
    while grid and not any(grid[0]):
        grid.pop(0)
    if len(grid) < 2:
        return None
    width = min(MAX_COLS, max(len(r) for r in grid))
    grid = [(r + [""] * width)[:width] for r in grid[:MAX_ROWS + 1]]
    head = [_clean_header(h) for h in grid[0]]
    # a helper column holding the sheet's row numbers ("Cột / Hàng": 2, 3, 4 …) is not data
    first = [r[0] for r in grid[1:]]
    if re.search(r"c[ộo]t|h[àa]ng|row", head[0], re.I) and all(re.fullmatch(r"\d+", v or "") for v in first):
        head, grid = head[1:], [r[1:] for r in grid]
    cols = [h or f"Cột {i}" for i, h in enumerate(head, 1)]
    rows = [[vp._cell(v) for v in r] for r in grid[1:]]
    while rows and not any(v not in ("", None) for v in rows[-1]):
        rows.pop()  # only trailing blank rows go; a blank row between two groups stays where it is
    if not any(any(v not in ("", None) for v in r) for r in rows):
        return None
    return {"id": "exercise_sample", "description": "Bảng dựng lại từ ảnh bài tập của người dùng",
            "columns": cols, "rows": rows, "refs": "exact"}


def grid_text(fx: dict, limit: int = 40) -> str:
    """The rebuilt table as the model sees it: Excel addresses, header row, first rows."""
    from ..sandbox.excel import col_letter
    cols = fx["columns"]
    out = ["Hàng | " + " | ".join(f"{col_letter(i)}" for i in range(1, len(cols) + 1)),
           "1 | " + " | ".join(str(c) for c in cols)]
    for n, r in enumerate(fx["rows"][:limit], start=2):
        out.append(f"{n} | " + " | ".join("" if v is None else str(v) for v in r))
    if len(fx["rows"]) > limit:
        out.append(f"… (tổng cộng {len(fx['rows'])} hàng dữ liệu, hàng 2 đến {len(fx['rows']) + 1})")
    return "\n".join(out)


# ---------------------------------------------------------------- the solution

class SolStep(BaseModel):
    task: str = Field(description="yêu cầu được giải ở bước này")
    header_cell: str = Field("", description="ô tiêu đề cột mới (vd I1), rỗng nếu không cần")
    header_text: str = ""
    range: str = Field(description="ô hoặc vùng nhận công thức, vd I2:I6 hoặc G8")
    formula: str = Field(description="công thức tiếng Anh, dấu phẩy, viết cho ô đầu tiên của vùng")
    explain: str = Field(description="giải thích ngắn bằng tiếng Việt vì sao công thức đúng")


ACTION_KINDS = ("filter", "sort_asc", "sort_desc", "highlight_rows", "bold", "fill_color")


class SolAction(BaseModel):
    task: str = Field(description="yêu cầu được làm ở bước này")
    kind: str = Field(description="filter | sort_asc | sort_desc | highlight_rows | bold | fill_color")
    range: str = Field(description="vùng áp dụng: cả bảng có tiêu đề cho filter/sort; vùng dữ liệu (không tiêu đề) "
                                   "cho highlight_rows; ô/vùng cần in đậm hoặc tô màu")
    column: str = Field("", description="sort: một ô trong cột làm khóa sắp xếp, vd F2")
    formula: str = Field("", description="highlight_rows: công thức điều kiện cho hàng đầu của vùng, vd =$D2=\"Bắt buộc\"")
    explain: str = ""


class Solution(BaseModel):
    steps: list[SolStep] = Field(default_factory=list)
    actions: list[SolAction] = Field(default_factory=list)
    unsolved: list[str] = Field(default_factory=list, description="yêu cầu Guider chưa làm được")
    example: str = Field("", description="tóm tắt cách giải, nêu rõ ô và công thức, tiếng Việt")


SOLVE_SYSTEM = (
    "Bạn giải bài tập Excel trên ĐÚNG bảng đã cho (địa chỉ ô ghi ở hàng 'Hàng' và cột đầu). Với mỗi yêu cầu "
    "tính toán, viết một công thức cho ô đầu tiên của vùng kết quả; Guider gõ công thức rồi nhấn Ctrl+Enter để "
    "điền cả vùng, nên tham chiếu tương đối theo hàng, dùng $ cho ô cố định. Cột kết quả mới đặt ngay bên phải "
    "bảng (cột trống đầu tiên) và có ô tiêu đề ở hàng 1; kết quả tổng/đếm đặt ở ô trống ngay dưới bảng. Không "
    "ghi đè dữ liệu có sẵn. Dùng tên hàm tiếng Anh và dấu phẩy. Kết quả đơn lẻ (tổng, đếm, trung bình…) đặt ở "
    "hàng trống dưới bảng (bỏ trống một hàng), mỗi kết quả một hàng: header_cell là ô bên trái ô kết quả, "
    "header_text là nhãn (vd 'Tổng số lượng'), range là ô kết quả. Vùng dữ liệu luôn tính hết tới hàng cuối của bảng.\n"
    "Yêu cầu không phải tính toán thì đưa vào actions với kind: filter (bật bộ lọc cho cả bảng), sort_asc / "
    "sort_desc (sắp xếp tăng/giảm theo một cột; column là một ô của cột đó), highlight_rows (tô màu cả hàng "
    "thỏa điều kiện; range là vùng dữ liệu không gồm tiêu đề, formula là điều kiện cho hàng đầu với $ trước cột), "
    "bold (in đậm), fill_color (tô nền vàng). Chỉ yêu cầu không làm được bằng các cách trên mới ghi vào unsolved. "
    "Một đề có thể vừa có steps vừa có actions.")


def fit_actions(fx: dict, sol: Solution) -> None:
    """Filter and sort work on the whole table; a highlight runs to the last row. The model often stops a row
    short (A1:G26 for a table ending at row 27, 11/11/2026), so the ranges are set from the table itself."""
    from ..sandbox.excel import col_letter
    last_col, last_row = col_letter(len(fx["columns"])), len(fx["rows"]) + 1
    for a in sol.actions:
        if a.kind in ("filter", "sort_asc", "sort_desc"):
            a.range = f"A1:{last_col}{last_row}"
        elif a.kind == "highlight_rows":
            m = re.match(r"\$?[A-Z]{1,3}\$?(\d+)", a.range.strip().upper())
            start_row = max(2, int(m.group(1))) if m else 2
            a.range = f"A{start_row}:{last_col}{last_row}"


def label_results(fx: dict, sol: Solution) -> None:
    """A single result under the table (a total, a count) gets its task as a label in the cell to its left, so the
    sheet reads "Tổng số lượng  1244" instead of a bare number (the model often leaves the label out, 11/11/2026).
    A result in column A gets its label to the right."""
    from ..sandbox.excel import col_letter
    last_row = len(fx["rows"]) + 1
    for st in sol.steps:
        if ":" in st.range:
            continue
        cell = _split(st.range)
        if cell is None or cell[1] <= last_row:
            continue
        col, row = cell
        head = _split(st.header_cell) if st.header_cell else None
        if head and head[1] == row:
            continue  # already labelled on its own row
        n = _col_num(col)
        st.header_cell = f"{col_letter(n - 1)}{row}" if n > 1 else f"{col_letter(n + 1)}{row}"
        st.header_text = (st.header_text.strip() or st.task.strip())[:60]


def _split(ref: str) -> tuple[str, int] | None:
    m = re.fullmatch(r"\$?([A-Z]{1,3})\$?(\d+)", ref.strip().upper())
    return (m.group(1), int(m.group(2))) if m else None


def _col_num(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def _sheet_ok(lab, fx: dict, sol: Solution) -> tuple[bool, list[str]]:
    """Fill the rebuilt table in a hidden Excel, enter every step the way the demonstration will, check results."""
    fit_actions(fx, sol)
    label_results(fx, sol)
    from ..sandbox.excel import fill_sheet
    from ..training.refit import en_separators
    ws = lab.wb.Worksheets(1)
    ws.Cells.Clear()
    fill_sheet(ws, fx)
    problems, seen = [], []
    width, height = len(fx["columns"]), len(fx["rows"]) + 1
    for i, s in enumerate(sol.steps, 1):
        s.formula = en_separators(s.formula.strip())
        if not s.formula.startswith("="):
            s.formula = "=" + s.formula
        try:
            rng = ws.Range(s.range)
        except Exception:
            problems.append(f"bước {i}: vùng {s.range!r} không hợp lệ")
            continue
        if int(rng.Row) <= height and int(rng.Column) <= width:
            problems.append(f"bước {i}: {s.range} ghi đè dữ liệu có sẵn của bảng")
            continue
        if s.header_cell and s.header_text:
            ws.Range(s.header_cell).Value = s.header_text
        try:
            rng.Formula2 = s.formula
        except Exception:
            try:
                rng.Formula = s.formula
            except Exception:
                problems.append(f"bước {i}: Excel không nhận công thức {s.formula}")
                continue
    lab.app.Calculate()
    for i, s in enumerate(sol.steps, 1):
        try:
            rng = ws.Range(s.range)
        except Exception:
            continue
        bad = [str(c.Address).replace("$", "") for c in rng.Cells if str(c.Text).startswith("#")]
        conditional = re.search(r"\b(COUNTIFS?|SUMIFS?|AVERAGEIFS?)\(", s.formula.upper())
        if bad:
            problems.append(f"bước {i}: {s.formula} báo lỗi ở {', '.join(bad[:3])} ({rng.Cells(1, 1).Text})")
        elif conditional and all(str(c.Text).strip() in ("0", "") for c in rng.Cells):
            problems.append(f"bước {i}: {s.formula} ra 0 — có thể sai cột hoặc sai chữ điều kiện; xem lại tên cột ở hàng 1")
        else:
            seen.append(f"{s.range}: {s.formula} → {rng.Cells(1, 1).Text}")
    if ws.CircularReference is not None:
        problems.append("có vòng lặp tham chiếu")
    spare = ws.Cells(1, width + 30)  # far from the table and the answers
    for i, a in enumerate(sol.actions, 1):
        if a.kind not in ACTION_KINDS:
            problems.append(f"thao tác {i}: kind {a.kind!r} không hỗ trợ")
            continue
        try:
            rng = ws.Range(a.range)
            if a.column:
                ws.Range(a.column)
        except Exception:
            problems.append(f"thao tác {i}: vùng {a.range!r} không hợp lệ")
            continue
        if a.kind == "highlight_rows":
            a.formula = en_separators(a.formula.strip())
            if not a.formula.startswith("="):
                a.formula = "=" + a.formula
            # evaluate the rule as Excel would for the first row: write it next to that row and read the result
            first = rng.Cells(1, 1)
            col = ws.Range(ws.Cells(int(first.Row), width + 30), ws.Cells(int(first.Row) + int(rng.Rows.Count) - 1,
                                                                          width + 30))
            try:
                col.Formula = a.formula  # written for the first row; Excel shifts relative rows down the column
                lab.app.Calculate()
                texts = [str(c.Text).upper() for c in col.Cells]
            except Exception:
                texts = ["#ERR"]
            finally:
                col.ClearContents()
            if any(t.startswith("#") or t not in ("TRUE", "FALSE") for t in texts):
                problems.append(f"thao tác {i}: điều kiện {a.formula} cho {texts[0]}, phải ra TRUE hoặc FALSE")
                continue
            if "TRUE" not in texts:
                problems.append(f"thao tác {i}: điều kiện {a.formula} không trúng hàng nào — có thể sai cột; "
                                "xem lại tên cột ở hàng 1")
                continue
        seen.append(f"{a.kind} {a.range}")
    spare.ClearContents()
    return not problems, problems or seen


def solve(fx: dict, tasks: list[str], timeout: float = 60) -> tuple[Solution, list[str]]:
    """A solution for this table, checked in a hidden Excel; one repair round with Excel's complaints."""
    from ..training.refit import FormulaLab
    schema = Solution.model_json_schema()
    from ..sandbox.excel import col_letter
    last_col, last_row = col_letter(len(fx["columns"])), len(fx["rows"]) + 1
    user = (f"Bảng (đã dựng lại trong Excel) chiếm A1:{last_col}{last_row}: tiêu đề ở hàng 1, dữ liệu hàng 2–{last_row}, "
            f"hàng trống đầu tiên dưới bảng là {last_row + 1}, cột trống đầu tiên bên phải là "
            f"{col_letter(len(fx['columns']) + 1)}.\n{grid_text(fx)}\n\nYêu cầu:\n" + "\n".join(f"- {t}" for t in tasks))
    with FormulaLab() as lab:
        last: list[str] = []
        for attempt in range(2):
            ask = user if not last else user + "\n\nLần trước Excel báo:\n" + "\n".join(last) + "\nHãy sửa."
            try:
                sol = Solution.model_validate_json(_text_json(SOLVE_SYSTEM, ask, schema, timeout))
            except (ValidationError, vp.ProblemError) as e:
                last = [f"trả lời không hợp lệ: {str(e)[:200]}"]
                continue
            if not sol.steps and not sol.actions:
                return sol, ["không có yêu cầu nào Guider làm được"]
            ok, notes = _sheet_ok(lab, fx, sol)
            log.info("exercise.solve", attempt=attempt, ok=ok, notes=notes[:6])
            if ok:
                return sol, notes
            last = notes
    raise ExerciseError("Guider chưa viết được lời giải chạy đúng trên bảng này. "
                        + ("Excel báo: " + "; ".join(last[:3]) if last else ""))


def to_plan(fx: dict, sol: Solution, title: str) -> Plan:
    """Keyboard-first: type each header, then each formula into its range with Ctrl+Enter (fills the range)."""
    steps: list[Step] = []
    for s in sol.steps:
        if s.header_cell and s.header_text:
            steps.append(Step(id=len(steps) + 1, intent="type_formula", value=s.header_text,
                              target=Target(names=[s.header_cell], control_type="Cell"),
                              expected=Expected(type="com_check", prop="cell.value", ref=s.header_cell, op="eq",
                                                value=s.header_text)))
        first = s.range.split(":")[0]
        steps.append(Step(id=len(steps) + 1, intent="type_formula", value=s.formula,
                          target=Target(names=[s.range], control_type="Cell"),
                          expected=Expected(type="com_check", prop="cell.formula_ok", ref=first, op="true"),
                          capture_result=True))
    for a in sol.actions:
        steps += action_steps(a, start=len(steps) + 1)
    lines = [f"{s.task}: chọn {s.range}, gõ {s.formula}" + (" rồi nhấn Ctrl+Enter để điền cả vùng" if ":" in s.range
             else " rồi nhấn Enter") + f". {s.explain}" for s in sol.steps]
    lines += [f"{a.task}: {ACTION_TEXT[a.kind].format(r=a.range, c=a.column, f=a.formula)}. {a.explain}".strip()
              for a in sol.actions]
    example = (sol.example.strip() + " " if sol.example.strip() else "") + " ".join(lines)
    if sol.unsolved:
        example += " Chưa làm mẫu được: " + "; ".join(sol.unsolved) + "."
    return Plan(task_canonical="exercise", app="excel", title=title, steps=steps, example=example)


ACTION_TEXT = {
    "filter": "chọn {r}, vào Data > Filter để bật bộ lọc rồi chọn giá trị cần lọc ở mũi tên trên tiêu đề",
    "sort_asc": "chọn ô {c}, vào Data > Sort A to Z",
    "sort_desc": "chọn ô {c}, vào Data > Sort Z to A",
    "highlight_rows": "chọn {r}, vào Home > Conditional Formatting > New Rule > Use a formula, gõ {f}, "
                      "Format > Fill chọn màu, OK hai lần",
    "bold": "chọn {r}, nhấn Ctrl+B",
    "fill_color": "chọn {r}, vào Home > Fill Color chọn màu vàng",
}


def _card_steps(card_id: str) -> list[dict]:
    from ..intent.knowledge import KnowledgePack
    import copy
    return copy.deepcopy(KnowledgePack("excel").by_id[card_id].raw["steps"])


def action_steps(a: SolAction, start: int) -> list[Step]:
    """One non-formula task as demonstrable steps: select the exact range, then the reviewed card's clicks."""
    sel = a.column if a.kind in ("sort_asc", "sort_desc") and a.column else a.range
    out = [Step(id=start, intent="select_range", target=Target(names=[sel], control_type="Cell"))]
    first = a.range.split(":")[0]
    if a.kind == "filter":
        raw = _card_steps("filter_on")
    elif a.kind == "sort_desc":
        raw = _card_steps("sort_desc")
        raw[-1]["expected"] = {"type": "none"}  # the card checks its own sample's column
    elif a.kind == "sort_asc":
        raw = _card_steps("sort_desc")
        raw[-1]["target"] = {"names": ["Sort A to Z"], "control_type": "Button", "automation_id": "SortAscendingExcel"}
        raw[-1]["expected"] = {"type": "none"}
    elif a.kind == "highlight_rows":
        raw = _card_steps("cf_row_formula")
        for s in raw:
            if s.get("intent") == "set_value":
                s["value"] = a.formula
    elif a.kind == "bold":
        raw = [{"intent": "key_combo", "value": "Ctrl+B",
                "expected": {"type": "com_check", "prop": "range.font.bold", "ref": first, "op": "true"},
                "capture_result": True}]
    else:  # fill_color
        raw = _card_steps("fill_color")
        for s in raw:
            exp = s.get("expected") or {}
            if exp.get("type") == "com_check" and exp.get("ref"):
                exp["ref"] = first
    for k, s in enumerate(raw, start=start + 1):
        s["id"] = k
        out.append(Step.model_validate(s))
    out[-1].capture_result = True
    return out


@dataclass
class ExerciseRead:
    image: Path
    fixture: dict
    tasks: list[str]
    solution: Solution
    checked: list[str]
    timings: dict = field(default_factory=dict)


def read_and_solve(image_src: str | Path, text: str, work: Path, notify=None) -> ExerciseRead:
    """notify(message): progress lines for the app (Gemini busy, falling back to the local model, solving…)."""
    global _notify
    _notify = notify
    t0 = time.monotonic()
    img = vp.prepare(image_src, work)
    schema = SeenExercise.model_json_schema()
    user = f"Người dùng ghi thêm: {text.strip() or '(không có)'}"
    seen, last = None, None
    for _ in range(2):
        try:
            seen = parse_seen(_vision(img, READ_SYSTEM, user, schema, 90))
            if table_fixture(seen.content) is not None:
                break
        except (ValidationError, vp.ProblemError, json.JSONDecodeError, TypeError) as e:
            last = e
            log.info("exercise.read_retry", error=repr(e)[:200])
    if seen is None:
        raise ExerciseError("Guider chưa đọc được bảng trong ảnh. Hãy chụp rõ hơn, gọn vào bảng.") from last
    if table_fixture(seen.content) is None:
        log.info("exercise.no_table", content=seen.content[:200])
    t_read = time.monotonic()
    if seen.app not in ("excel", ""):
        raise ExerciseError("Chế độ Giải bài tập hiện chỉ làm bài Excel (bảng tính).")
    fx = table_fixture(seen.content)
    if fx is None:
        raise ExerciseError("Guider không thấy bảng nào trong ảnh. Hãy chụp cả bảng, có dòng tiêu đề.")
    tasks = [t for t in seen.tasks if t.strip()]
    if text.strip():
        tasks.append(text.strip())
    if not tasks:
        raise ExerciseError("Guider đã đọc được bảng nhưng không thấy yêu cầu. Hãy gõ đề bài vào ô chat "
                            "(vd: Tính lương = Lương CB / 26 × Ngày công).")
    _say(f"Đã dựng lại bảng {len(fx['rows'])} hàng × {len(fx['columns'])} cột, đang viết lời giải và thử trong Excel…")
    sol, checked = solve(fx, tasks)
    res = ExerciseRead(img, fx, tasks, sol, checked, {"read": round(t_read - t0, 2),
                                                       "solve": round(time.monotonic() - t_read, 2)})
    log.info("exercise.read", rows=len(fx["rows"]), cols=len(fx["columns"]), tasks=len(tasks),
             steps=len(sol.steps), actions=len(sol.actions), **res.timings)
    return res
