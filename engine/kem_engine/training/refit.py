"""Relearn the cards whose demonstration failed: one sample file does not fit every
lesson, so try others, build one for the card, and correct names from what Office really shows.

Two repairs, both checked by Office before a card is learned:
  * Formula cards whose result was an error (#VALUE!, #N/A…) on the default table. A hidden Excel tries the
    formula on every Excel sample file in milliseconds; when none fits, the training model builds a small
    table for that card (and may move the cell references onto it), and the hidden Excel checks it again.
  * Steps whose button was not found. The demonstration records the names that were on screen at that moment;
    the step takes the closest real name, or the model picks one from that list (never a name it invents).
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import structlog
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from ..intent.knowledge import fold
from ..llm.providers.base import LLMError
from ..sandbox.office import FIXTURES, load_fixture

log = structlog.get_logger()

EXCEL_FIXTURES = ("sales_table_basic", "numbers_grid", "grades_basic", "payroll_basic", "inventory_lookup",
                  "loan_basic")
CARD_FIXTURES = FIXTURES / "cards"
MAX_TRIES = 2  # relearning rounds per card before it stays in the waiting list for a person
BLOCKED = "chặn bởi SafetyGuard"  # refused on purpose (needs an account, the network…): never retried


def is_formula_card(card: dict) -> bool:
    return any(s.get("intent") == "type_formula" for s in card["steps"])


def formula_steps(card: dict) -> list[tuple[str, str]]:
    return [(s["target"]["names"][0], s["value"]) for s in card["steps"] if s.get("intent") == "type_formula"]


# ---- formulas ---------------------------------------------------------------------------------------------
class FormulaLab:
    """A hidden, never-saved Excel used only to evaluate formulas on sample tables. Nothing is shown or typed."""

    def __enter__(self):
        import win32com.client

        from ..env import win32
        from ..sandbox import recovery
        self.app = win32com.client.DispatchEx("Excel.Application")
        self.app.Visible = False
        self.app.DisplayAlerts = False
        self.app.ScreenUpdating = False
        self.wb = self.app.Workbooks.Add()
        self.pid = win32.window_pid(int(self.app.Hwnd))
        recovery.record("Excel", self.pid, "XLMAIN", str(self.wb.Name))  # cleaned up if the engine dies
        return self

    def __exit__(self, *exc):
        from ..sandbox import recovery
        try:
            self.wb.Close(SaveChanges=False)
            self.app.Quit()
        except Exception as e:
            log.warning("formula_lab.quit_failed", error=repr(e))
        self.wb = self.app = None
        recovery.forget(self.pid)

    def run(self, fx: dict, steps: list[tuple[str, str]]) -> tuple[bool, list[str]]:
        """Fill the table, type each formula, recalculate. OK when every formula gives a value, not an error."""
        from ..sandbox.excel import fill_sheet
        ws = self.wb.Worksheets(1)
        ws.Cells.Clear()
        fill_sheet(ws, fx)
        texts = []
        for cell, formula in steps:
            r = ws.Range(cell)
            try:
                r.Formula2 = formula
            except Exception:
                try:
                    r.Formula = formula
                except Exception:
                    return False, texts + [f"{cell}: Excel không nhận công thức"]
        self.app.Calculate()
        ok = True
        for cell, _ in steps:
            r = ws.Range(cell)
            text = str(r.Text).strip()
            texts.append(f"{cell}={text}")
            if not r.HasFormula or text.startswith("#"):
                ok = False
        if ok and ws.CircularReference is not None:
            return False, texts + ["vòng lặp tham chiếu"]
        return ok, texts


def _meaningful(texts: list[str]) -> bool:
    return all(t.split("=", 1)[1] not in ("", "0", "FALSE") for t in texts if "=" in t)


def best_fixture(lab: FormulaLab, card: dict) -> tuple[str | None, list[str]]:
    """The first sample file on which the card's formulas work; one with non-zero results wins."""
    steps, fallback, last = formula_steps(card), None, []
    order = [card.get("fixture_id")] + [f for f in EXCEL_FIXTURES if f != card.get("fixture_id")]
    for fid in order:
        if not fid:
            continue
        try:
            ok, texts = lab.run(load_fixture(fid), steps)
        except Exception as e:
            ok, texts = False, [repr(e)[:80]]
        last = texts
        if ok and _meaningful(texts):
            return fid, texts
        if ok and fallback is None:
            fallback = (fid, texts)
    return (fallback if fallback else (None, last))


class FxBlock(BaseModel):
    anchor: str = Field(description="Ô góc trên trái của bảng phụ, ví dụ J1")
    values: list[list[str | float | int | None]]


class FxStep(BaseModel):
    cell: str = Field(description="Ô gõ công thức, ví dụ F2")
    formula: str = Field(description="Công thức bắt đầu bằng =, tên hàm tiếng Anh, dấu phẩy ngăn đối số")


class FxOut(BaseModel):
    columns: list[str] = Field(description="Tiêu đề cột ở dòng 1, bắt đầu từ cột A")
    rows: list[list[str | float | int | None]] = Field(description="Tối đa 20 dòng dữ liệu bịa")
    blocks: list[FxBlock] = Field(default_factory=list, description="Bảng tra cứu hoặc ô điều kiện, nếu cần")
    names: dict[str, str] = Field(default_factory=dict,
                                  description="Tên vùng công thức dùng, ví dụ {\"DoanhSo\": \"$D$2:$D$21\"}")
    steps: list[FxStep]
    example: str = Field(description="Một câu ví dụ tiếng Việt khớp với bảng và công thức này")


FX_SYSTEM = (
    "Bạn dựng một bảng Excel mẫu nhỏ (dữ liệu bịa, tiếng Việt) để dạy đúng một công thức. Giữ nguyên hàm và "
    "ý nghĩa của công thức; được phép đổi địa chỉ ô cho khớp bảng. Bảng bắt đầu ở A1 (dòng 1 là tiêu đề), tối "
    "đa 10 cột và 20 dòng; ô gõ công thức phải nằm ngoài vùng dữ liệu nó tham chiếu. Ngày viết dạng "
    "\"date:YYYY-MM-DD\". Công thức dùng tên hàm tiếng Anh và dấu phẩy. Kết quả phải là giá trị có nghĩa, "
    "không phải lỗi hay 0. Nếu công thức dùng tên vùng (như DoanhSo) thì giữ tên đó và khai báo trong 'names'. "
    "Chỉ trả JSON.")


def fixture_id_for(card: dict) -> str:
    return "card_" + re.sub(r"[^a-z0-9_]", "_", card["id"].lower())[:60]


def build_fixture(lab: FormulaLab, llm, card: dict, attempts: int = 2) -> tuple[dict | None, str]:
    """Ask the model for a table that fits the card; keep it only when the hidden Excel computes it."""
    feedback = ""
    for _ in range(attempts):
        user = json.dumps({"title": card["title"], "example": card.get("example", ""),
                           "formulas": [{"cell": c, "formula": f} for c, f in formula_steps(card)],
                           "previous_result": feedback}, ensure_ascii=False)
        try:
            out = llm.complete(FX_SYSTEM, user, FxOut, max_tokens=3000)
        except LLMError as e:
            return None, f"không dựng được bảng mẫu: {e}"[:160]
        steps = [(s.cell.replace("$", "").upper().strip(), s.formula.strip()) for s in out.steps]
        if not steps or len(steps) != len(formula_steps(card)) or not all(f.startswith("=") for _, f in steps):
            feedback = "số công thức phải giữ nguyên và bắt đầu bằng ="
            continue
        fx = {"id": fixture_id_for(card), "description": f"Bảng mẫu dựng cho thẻ: {card['title']} (dữ liệu bịa)",
              "columns": out.columns[:10], "rows": [r[:10] for r in out.rows[:20]],
              "blocks": [b.model_dump() for b in out.blocks[:3]],
              "names": {k: v for k, v in out.names.items() if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,40}", k)}}
        try:
            ok, texts = lab.run(fx, steps)
        except Exception as e:
            ok, texts = False, [repr(e)[:80]]
        if ok and _meaningful(texts):
            new = copy.deepcopy(card)
            it = iter(steps)
            for s in new["steps"]:
                if s.get("intent") == "type_formula":
                    cell, formula = next(it)
                    s["target"]["names"] = [cell]
                    s["value"] = formula
                    if (s.get("expected") or {}).get("ref"):
                        s["expected"]["ref"] = cell
            new["fixture_id"] = fx["id"]
            new["example"] = out.example.strip() or card.get("example", "")
            return {"card": new, "fixture": fx}, ", ".join(texts)
        feedback = "; ".join(texts)
    return None, f"bảng mẫu tự dựng vẫn lỗi: {feedback}"[:160]


def save_card_fixture(fx: dict) -> None:
    CARD_FIXTURES.mkdir(parents=True, exist_ok=True)
    (CARD_FIXTURES / f"{fx['id']}.json").write_text(json.dumps(fx, ensure_ascii=False, indent=1), encoding="utf-8")


def en_separators(formula: str) -> str:
    """Books in Vietnamese write =ROUND(D2; -1); Guider types into English Excel, which wants commas."""
    out, quoted = [], False
    for ch in formula:
        quoted = not quoted if ch == '"' else quoted
        out.append("," if ch == ";" and not quoted else ch)
    return "".join(out)


def refit_formula(lab: FormulaLab, llm, card: dict) -> tuple[dict | None, dict | None, str]:
    """(card that should now work, fixture to save or None, what happened)."""
    card = copy.deepcopy(card)
    for s in card["steps"]:
        if s.get("intent") == "type_formula":
            s["value"] = en_separators(s["value"])
    fid, texts = best_fixture(lab, card)
    if fid:
        new = card
        new["fixture_id"] = fid
        return new, None, f"chạy được trên file mẫu {fid}: {', '.join(texts)}"
    built, why = build_fixture(lab, llm, card)
    if built:
        return built["card"], built["fixture"], f"dựng bảng mẫu riêng: {why}"
    return None, None, why


# ---- names ------------------------------------------------------------------------------------------------
class NamePick(BaseModel):
    pick: str | None = Field(description="Đúng một tên trong 'seen' làm được việc của bước, hoặc null")
    open_first: str | None = Field(default=None, description="Tên trong 'seen' cần mở trước (menu, nhóm), hoặc null")


NAME_SYSTEM = (
    "Một bước hướng dẫn Office không tìm thấy nút theo tên đã ghi. 'seen' là các phần tử đang hiện trên màn hình "
    "(tên|loại). Chọn tên trong 'seen' làm đúng việc của bước. Nếu nút nằm trong một menu hay nhóm chưa mở, trả "
    "open_first là tên menu/nhóm đó (cũng phải có trong 'seen'). Không bịa tên. Chỉ trả JSON.")


def _norm(s: str) -> str:
    return fold(s).rstrip(".…: ").strip()


def repair_names(llm, card: dict, missing: dict) -> tuple[dict | None, str]:
    """missing: {"want", "intent", "control_type", "seen": ["name|type", ...]} from the demonstration."""
    want = missing["want"]
    idx = next((i for i, s in enumerate(card["steps"]) if (s.get("target") or {}).get("names", [None])[0] == want),
               None)
    seen = [x.rsplit("|", 1) for x in missing.get("seen", []) if "|" in x]
    if idx is None or not seen:
        return None, "không có danh sách tên trên màn hình để so"
    names = {n for n, _ in seen}
    scored = sorted(((fuzz.WRatio(_norm(want), _norm(n)), n) for n in names if _norm(n)), reverse=True)
    pick, open_first = None, None
    if scored and scored[0][0] >= 90 and scored[0][1] != want:
        pick = scored[0][1]
    elif llm is not None:
        user = json.dumps({"task": card["title"], "step": card["steps"][idx], "seen": [f"{n}|{t}" for n, t in seen][:250]},
                          ensure_ascii=False)
        try:
            out = llm.complete(NAME_SYSTEM, user, NamePick, max_tokens=400)
        except LLMError as e:
            return None, f"không chọn được tên: {e}"[:120]
        pick = out.pick if out.pick in names and out.pick != want else None
        open_first = out.open_first if out.open_first in names else None
    if not pick and not open_first:
        return None, f"không có nút nào trên màn hình giống '{want}'"
    new = copy.deepcopy(card)
    st = new["steps"][idx]
    if pick:
        st["target"]["names"] = [pick] + [n for n in st["target"]["names"] if n != pick][:3]
        st["target"].pop("automation_id", None)
    if open_first:
        ctype = next(t for n, t in seen if n == open_first)
        new["steps"].insert(idx, {"id": 0, "intent": "expand",
                                  "target": {"names": [open_first], "control_type": ctype},
                                  "expected": {"type": "expanded"}})
    for i, s in enumerate(new["steps"], start=1):
        s["id"] = i
    return new, f"đổi '{want}' → '{pick or want}'" + (f", mở '{open_first}' trước" if open_first else "")


def card_fixture_files() -> list[Path]:
    return sorted(CARD_FIXTURES.glob("card_*.json")) if CARD_FIXTURES.exists() else []
