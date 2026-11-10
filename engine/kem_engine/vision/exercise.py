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
    "- content: mỗi hàng một dòng, các ô cách nhau bằng ' | ', hàng tiêu đề trước; chép đủ mọi hàng và cột "
    "(tối đa 40 hàng, 15 cột), giữ nguyên chữ, dấu tiếng Việt, số (không thêm dấu phân cách hàng nghìn).\n"
    "- Nếu ảnh có cột ghi số hàng (vd 'Cột / Hàng' với 2, 3, 4…) thì bỏ cột đó; nếu tiêu đề có chữ cột như "
    "'B (Mã NV)' thì chỉ ghi 'Mã NV'. Ô trống ghi rỗng.\n"
    "- tasks: các yêu cầu/câu hỏi của bài tập viết trên ảnh (vd 'Tính lương = Lương CB/26*Ngày công'), giữ "
    "nguyên ý; không có thì để danh sách rỗng.\n"
    "- app: excel nếu là bảng tính; word/powerpoint/other nếu không phải.")


def _vision(image: Path, system: str, user: str, schema: dict, timeout: float, max_tokens: int = 2500) -> str:
    """Gemini when allowed (a few seconds), else the local vision model (slow on CPU)."""
    if vp.cloud_enabled():
        try:
            import openai

            from ..llm.config import LLMConfig
            conf = LLMConfig.load().providers.get("gemini")
            client = openai.OpenAI(base_url=conf.base_url, api_key=conf.api_key(), timeout=timeout, max_retries=0)
            url = "data:image/png;base64," + base64.b64encode(image.read_bytes()).decode()
            r = client.chat.completions.create(
                model=conf.models[0], temperature=0.1, max_tokens=max_tokens, timeout=timeout,
                **({"reasoning_effort": conf.reasoning_effort} if conf.reasoning_effort else {}),
                messages=[{"role": "system", "content": system + " Trả về JSON: " + json.dumps(schema, ensure_ascii=False)},
                          {"role": "user", "content": [{"type": "text", "text": user},
                                                       {"type": "image_url", "image_url": {"url": url}}]}],
                response_format={"type": "json_object"})
            return r.choices[0].message.content or ""
        except Exception as e:
            log.info("exercise.cloud_failed", error=repr(e)[:200])
    conf = vp.VisionConf.load()
    img = base64.b64encode(image.read_bytes()).decode()
    return vp._ollama(conf, [{"role": "system", "content": system},
                             {"role": "user", "content": user, "images": [img]}], schema,
                      max(timeout, conf.timeout_s), max_tokens=max_tokens)


def _text_json(system: str, user: str, schema: dict, timeout: float, max_tokens: int = 2000) -> str:
    """Writing the solution: text only (the table as rebuilt, the tasks). Gemini when allowed, else local."""
    if vp.cloud_enabled():
        try:
            import openai

            from ..llm.config import LLMConfig
            conf = LLMConfig.load().providers.get("gemini")
            client = openai.OpenAI(base_url=conf.base_url, api_key=conf.api_key(), timeout=timeout, max_retries=0)
            r = client.chat.completions.create(
                model=conf.models[0], temperature=0.1, max_tokens=max_tokens, timeout=timeout,
                **({"reasoning_effort": conf.reasoning_effort} if conf.reasoning_effort else {}),
                messages=[{"role": "system", "content": system + " Trả về JSON: " + json.dumps(schema, ensure_ascii=False)},
                          {"role": "user", "content": user}], response_format={"type": "json_object"})
            return r.choices[0].message.content or ""
        except Exception as e:
            log.info("exercise.cloud_text_failed", error=repr(e)[:200])
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
    grid = [r for r in grid if any(r) and not all(set(c) <= set("-: ") for c in r)]
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
    rows = [r for r in rows if any(v not in ("", None) for v in r)]
    if not rows:
        return None
    return {"id": "exercise_sample", "description": "Bảng dựng lại từ ảnh bài tập của người dùng",
            "columns": cols, "rows": rows, "refs": "exact"}


def grid_text(fx: dict, limit: int = 12) -> str:
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


class Solution(BaseModel):
    steps: list[SolStep] = Field(default_factory=list)
    unsolved: list[str] = Field(default_factory=list, description="yêu cầu không giải được bằng công thức")
    example: str = Field("", description="tóm tắt cách giải, nêu rõ ô và công thức, tiếng Việt")


SOLVE_SYSTEM = (
    "Bạn giải bài tập Excel trên ĐÚNG bảng đã cho (địa chỉ ô ghi ở hàng 'Hàng' và cột đầu). Với mỗi yêu cầu "
    "tính toán, viết một công thức cho ô đầu tiên của vùng kết quả; Guider gõ công thức rồi nhấn Ctrl+Enter để "
    "điền cả vùng, nên tham chiếu tương đối theo hàng, dùng $ cho ô cố định. Cột kết quả mới đặt ngay bên phải "
    "bảng (cột trống đầu tiên) và có ô tiêu đề ở hàng 1; kết quả tổng/đếm đặt ở ô trống ngay dưới bảng. Không "
    "ghi đè dữ liệu có sẵn. Dùng tên hàm tiếng Anh và dấu phẩy. Yêu cầu không phải tính toán (định dạng, vẽ "
    "biểu đồ, sắp xếp…) ghi vào unsolved.")


def _sheet_ok(lab, fx: dict, sol: Solution) -> tuple[bool, list[str]]:
    """Fill the rebuilt table in a hidden Excel, enter every step the way the demonstration will, check results."""
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
        if bad:
            problems.append(f"bước {i}: {s.formula} báo lỗi ở {', '.join(bad[:3])} ({rng.Cells(1, 1).Text})")
        else:
            seen.append(f"{s.range}: {s.formula} → {rng.Cells(1, 1).Text}")
    if ws.CircularReference is not None:
        problems.append("có vòng lặp tham chiếu")
    return not problems, problems or seen


def solve(fx: dict, tasks: list[str], timeout: float = 60) -> tuple[Solution, list[str]]:
    """A solution for this table, checked in a hidden Excel; one repair round with Excel's complaints."""
    from ..training.refit import FormulaLab
    schema = Solution.model_json_schema()
    user = f"Bảng (đã dựng lại trong Excel):\n{grid_text(fx)}\n\nYêu cầu:\n" + "\n".join(f"- {t}" for t in tasks)
    with FormulaLab() as lab:
        last: list[str] = []
        for attempt in range(2):
            ask = user if not last else user + "\n\nLần trước Excel báo:\n" + "\n".join(last) + "\nHãy sửa."
            try:
                sol = Solution.model_validate_json(_text_json(SOLVE_SYSTEM, ask, schema, timeout))
            except (ValidationError, vp.ProblemError) as e:
                last = [f"trả lời không hợp lệ: {str(e)[:200]}"]
                continue
            if not sol.steps:
                return sol, ["không có yêu cầu tính toán nào"]
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
    lines = [f"{s.task}: chọn {s.range}, gõ {s.formula}" + (" rồi nhấn Ctrl+Enter để điền cả vùng" if ":" in s.range
             else " rồi nhấn Enter") + f". {s.explain}" for s in sol.steps]
    example = (sol.example.strip() + " " if sol.example.strip() else "") + " ".join(lines)
    if sol.unsolved:
        example += " Chưa làm mẫu (không phải công thức): " + "; ".join(sol.unsolved) + "."
    return Plan(task_canonical="exercise", app="excel", title=title, steps=steps, example=example)


@dataclass
class ExerciseRead:
    image: Path
    fixture: dict
    tasks: list[str]
    solution: Solution
    checked: list[str]
    timings: dict = field(default_factory=dict)


def read_and_solve(image_src: str | Path, text: str, work: Path) -> ExerciseRead:
    t0 = time.monotonic()
    img = vp.prepare(image_src, work)
    schema = SeenExercise.model_json_schema()
    user = f"Người dùng ghi thêm: {text.strip() or '(không có)'}"
    try:
        seen = SeenExercise.model_validate_json(_vision(img, READ_SYSTEM, user, schema, 60))
    except ValidationError as e:
        raise ExerciseError("Guider chưa đọc được bảng trong ảnh. Hãy chụp rõ hơn, gọn vào bảng.") from e
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
    sol, checked = solve(fx, tasks)
    res = ExerciseRead(img, fx, tasks, sol, checked, {"read": round(t_read - t0, 2),
                                                       "solve": round(time.monotonic() - t_read, 2)})
    log.info("exercise.read", rows=len(fx["rows"]), cols=len(fx["columns"]), tasks=len(tasks),
             steps=len(sol.steps), **res.timings)
    return res
