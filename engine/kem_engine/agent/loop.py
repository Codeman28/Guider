"""Observe-act agent (ADR-0007).

Cards and one-shot plans only cover tasks somebody wrote down. For anything else Guider works like a person
at the keyboard: look at the sandbox (the controls on screen, the sheet or document, a screenshot), choose ONE
action, do it through the same actuator and SafetyGuard as a card step, look again, and so on until the goal
is reached. A failed attempt is taken out of the tutorial and reported back so the next choice can differ.
When the agent says it is done, a final look at the result decides whether the tutorial says "done" or
"partly done". A task finished this way is saved as a card of its own, so the next time is a replay.

The model is Gemini (vision) with retries across models; the picture sent is the sandbox window only, with
the account area blurred (same redaction as the tutorial screenshots).
"""
from __future__ import annotations

import base64
import io
import json
import re
import time
from dataclasses import dataclass, field

import structlog
from pydantic import BaseModel, Field, ValidationError

from ..models import Expected, Step, Target

log = structlog.get_logger()

MAX_ACTIONS = 16
MAX_FAILS_IN_A_ROW = 3
ACTIONABLE = {"Button", "SplitButton", "MenuItem", "TabItem", "ListItem", "CheckBox", "RadioButton", "ComboBox",
              "Edit", "Hyperlink", "TreeItem", "Spinner"}
MAX_ELEMENTS = 260


class Decision(BaseModel):
    thought: str = Field("", description="ngắn: đang thấy gì, bước tiếp theo để làm gì")
    action: str = Field(description="click | type | keys | select | set_value | done | give_up")
    id: int = Field(0, description="click/set_value: số # của control trong danh sách")
    name: str = Field("", description="click/set_value: tên control y như trong danh sách")
    control_type: str = Field("", description="click/set_value: loại control y như trong danh sách")
    cell: str = Field("", description="type/select (Excel): ô hoặc vùng, vd B2 hoặc A1:D21")
    value: str = Field("", description="type: chữ hoặc công thức (tiếng Anh, dấu phẩy); keys: tổ hợp phím vd Ctrl+B; "
                                      "set_value: chữ cần nhập")
    expect: str = Field("none", description="sau khi click: dialog | menu | tab | none")


class Verdict(BaseModel):
    achieved: bool
    reason: str = ""


SYSTEM = (
    "Bạn là Guider, đang tự làm mẫu một việc trong Microsoft {app} (giao diện tiếng Anh) trên một file mẫu, để "
    "chụp lại thành bài hướng dẫn. Mỗi lượt bạn nhận: mục tiêu, các bước đã làm (và kết quả), trạng thái file, "
    "danh sách control đang hiện trên màn hình (tên | loại | cửa sổ) và ảnh chụp. Hãy chọn MỘT hành động tiếp theo.\n"
    "- click: bấm control có trong danh sách: ghi id = số # của nó (kèm tên, loại). Tab ribbon là TabItem; nút mở "
    "menu thì expect=menu; nút có '...' mở hộp thoại thì expect=dialog.\n"
    "- type: Excel: gõ chữ hoặc công thức vào ô/vùng ghi trong cell (vùng thì Guider nhấn Ctrl+Enter để điền cả vùng); "
    "Word/PowerPoint: gõ chữ; ghi cell là chỗ gõ (Word: p3 = đoạn 3; PowerPoint: s4.1 = khung chữ 1 của slide 4) để "
    "Guider chọn chỗ đó trước, chữ gõ vào sẽ THAY nội dung đang chọn.\n"
    "- keys: nhấn MỘT tổ hợp phím tắt của Office, ghi trong value (vd Ctrl+B, Ctrl+Shift+L, F4). KHÔNG dùng chuỗi "
    "phím Alt (Alt,H,O…) và không dùng phím của Windows; khi đó hãy click.\n"
    "- select: chọn trước khi bấm nút định dạng: Excel ô/vùng (B2, A1:D21); Word đoạn (p3, p2-p4, all); "
    "PowerPoint slide (s2) hoặc khung chữ (s2.1). Ghi trong cell.\n"
    "- set_value: nhập chữ vào ô nhập (Edit/ComboBox) trong hộp thoại; ghi id của ô nhập.\n"
    "- done: khi trạng thái/ảnh cho thấy mục tiêu đã đạt. give_up: khi chắc chắn không làm được.\n"
    "Ưu tiên cách người dùng hay làm nhất: gõ hàm, phím tắt quen thuộc, rồi mới tới ribbon. Không lặp lại hành động "
    "vừa thất bại y hệt. Không đóng file, không lưu, không mở file khác, không dùng File/Backstage.\n"
    "Kinh nghiệm Office: {tips}\n"
    "Nếu một bước làm file thay đổi sai ý (dữ liệu bị đẩy lệch, đổi nhầm chỗ), nhấn Ctrl+Z để hoàn tác NGAY rồi mới "
    "thử cách khác. Sau mỗi bước, đọc dòng 'file thay đổi' trong kết quả: nếu mục tiêu đã đạt thì chọn done NGAY, "
    "không làm thêm "
    "(vd chèn một cột thì chỉ chèn một lần). Một nút có mũi tên (SplitButton) bấm vào phần thân là làm luôn, "
    "không mở menu.")

VERDICT = ("So sánh mục tiêu với trạng thái file và ảnh chụp cuối cùng. achieved=true chỉ khi mục tiêu thật sự đã "
           "đạt trên file (đúng ô, đúng định dạng, đúng kết quả) và KHÔNG làm thừa (vd yêu cầu chèn một cột mà file "
           "có thêm nhiều cột trống là chưa đạt), và dữ liệu cũ còn nguyên vị trí, không bị đẩy lệch hay mất, trừ khi "
           "mục tiêu yêu cầu thay đổi nó (so với trạng thái ban đầu). 'Trước/sau cột X' nghĩa là ngay sát cột X. "
           "reason: một câu tiếng Việt.")

TIPS = {
    "excel": "chọn đúng ô/vùng trước rồi mới bấm nút hay phím tắt; chèn/xóa cả cột hay hàng thì chọn cả cột/hàng "
             "(vd D1:D21 hoặc D:D) rồi Home > Insert/Delete; nút Insert/Delete bấm phần thân sẽ làm theo vùng đang chọn; "
             "công thức tiếng Anh, dấu phẩy.",
    "word": "chọn đoạn trước (select p3 / p2-p4 / all) rồi mới định dạng; đầu trang/chân trang ở Insert > Header/Footer "
            "rồi đóng bằng Close Header and Footer; hướng giấy, lề ở Layout.",
    "powerpoint": "slide mới (Home > New Slide hoặc Ctrl+M) được chèn NGAY SAU slide đang chọn: muốn thêm ở cuối thì "
                  "select slide cuối (vd s3) trước; gõ tiêu đề: type với cell sN.1; hiệu ứng chuyển trang ở Transitions, "
                  "hiệu ứng cho chữ/hình ở Animations (chọn khung chữ trước).",
}

GLOBAL_KEYS = {"ctrl+z", "ctrl+y", "escape", "esc", "enter", "f4"}  # do not depend on the selection


def _cell_flags(cell) -> list[str]:
    """Formatting the model needs to judge a result: what a person would see on the cell."""
    out = []
    try:
        f = cell.DisplayFormat
        if f.Font.Bold:
            out.append("đậm")
        if f.Font.Italic:
            out.append("nghiêng")
        if int(f.Font.Underline) not in (-4142, 0):
            out.append("gạch dưới")
        size = float(f.Font.Size)
        if abs(size - 11) > 0.1:
            out.append(f"cỡ {size:g}")
        color = int(f.Font.Color)
        if color != 0:
            out.append(f"chữ#{color:06x}")
        fill = int(f.Interior.Color)
        if fill != 16777215:
            out.append(f"nền#{fill:06x}")
        edges = [int(f.Borders(i).LineStyle) for i in (7, 8, 9, 10)]  # left, top, bottom, right
        if any(e not in (-4142, 0) for e in edges):
            out.append("viền " + ("4 cạnh" if all(e not in (-4142, 0) for e in edges) else "một phần"))
        h = int(f.HorizontalAlignment)
        if h in (-4108, 7):
            out.append("căn giữa")
        elif h == -4152:
            out.append("căn phải")
        nf = str(cell.NumberFormat)
        if nf != "General":
            out.append(f"định dạng {nf}")
        if cell.MergeCells:
            out.append(f"gộp {str(cell.MergeArea.Address).replace('$', '')}")
        if cell.WrapText:
            out.append("xuống dòng")
    except Exception:
        pass
    return out


def _safe(fn, default="?"):
    try:
        return fn()
    except Exception:
        return default


def _word_para_flags(p) -> str:
    """Font and layout of one paragraph, as a person would see it (9999999 = mixed in Word)."""
    f, out = p.Range.Font, []
    out.append(f"font {_safe(lambda: str(f.Name))}")
    size = _safe(lambda: float(f.Size))
    out.append(f"cỡ {size:g}" if isinstance(size, float) and size < 9999 else "cỡ lẫn")
    color = _safe(lambda: int(f.Color))
    if isinstance(color, int) and color not in (-16777216, 0, 9999999):
        out.append(f"màu #{color & 0xFFFFFF:06x} (BGR)")
    for name, flag in (("đậm", "Bold"), ("nghiêng", "Italic")):
        if _safe(lambda: getattr(f, flag)) in (True, -1):
            out.append(name)
    if _safe(lambda: int(f.Underline)) not in (0, "?"):
        out.append("gạch dưới")
    align = {0: "trái", 1: "giữa", 2: "phải", 3: "đều"}.get(_safe(lambda: int(p.Alignment)), "")
    if align and align != "trái":
        out.append(f"căn {align}")
    hl = _safe(lambda: int(p.Range.HighlightColorIndex))
    if hl not in (0, "?", 9999999):
        out.append("tô sáng")
    return ", ".join(out)


def _word_extras(d) -> str:
    """What a Word task usually changes beyond the paragraph text."""
    sec = d.Sections(1)
    head = _safe(lambda: str(sec.Headers(1).Range.Text).strip()[:80], "")
    foot = _safe(lambda: str(sec.Footers(1).Range.Text).strip()[:80], "")
    pnum = _safe(lambda: int(sec.Footers(1).PageNumbers.Count) + int(sec.Headers(1).PageNumbers.Count), 0)
    fields = _safe(lambda: int(sec.Footers(1).Range.Fields.Count) + int(sec.Headers(1).Range.Fields.Count), 0)
    ps = d.PageSetup
    parts = [f"đầu trang: {head!r}", f"chân trang: {foot!r}", f"số trang: {pnum} (trường trong đầu/chân trang: {fields})",
             f"hướng giấy: {'ngang' if _safe(lambda: int(ps.Orientation)) == 1 else 'dọc'}",
             f"lề trái/phải/trên/dưới (pt): {_safe(lambda: (ps.LeftMargin, ps.RightMargin, ps.TopMargin, ps.BottomMargin))}",
             f"{_safe(lambda: int(d.Tables.Count), 0)} bảng", f"{_safe(lambda: int(d.InlineShapes.Count), 0)} ảnh",
             f"{_safe(lambda: int(d.TablesOfContents.Count), 0)} mục lục",
             f"số cột: {_safe(lambda: int(ps.TextColumns.Count), 1)}"]
    return ", ".join(parts)


NOT_FOR_AGENT = {"Close", "Minimize", "Maximize", "Restore Down", "Restore", "File Tab", "File",
                 "Ribbon Display Options", "Collapse the Ribbon", "Share", "AutoSave", "Save"}


def _pick_type(ct: str) -> str:
    return ct if ct in ACTIONABLE else ""


@dataclass
class Agent:
    goal: str
    app: str = "excel"
    history: list[dict] = field(default_factory=list)
    verdict: Verdict | None = None
    budget_s: float = 110.0  # wall-clock for the whole look-act loop (tutorials stay under ~2 min)
    calls: int = 0
    gave_up: str = ""
    shown: dict = field(default_factory=dict)  # id → element listed in the last look
    initial_state: str = ""  # the document before the agent's first action (the judge compares against it)
    judge_only: bool = False  # replay of a cleaned path: no new actions, only the final check
    reject: str = ""  # why the last decision could not become a step (told to the model)
    main_hwnd: int = 0  # the sandbox frame (ribbon controls live under it)
    replay_failed: bool = False  # the cleaned path did not reach the goal on its own (not learned)

    # ---------------------------------------------------------------- what the agent sees
    def observe(self, s, detail: bool = False) -> tuple[str, str]:
        """(text view, PNG data URL) of the sandbox for the model."""
        from ..annotate.redact import fallback_identity_rect, redact
        from ..capture.printwindow import capture_composite
        from ..models import Rect
        from ..uia.snapshot import snapshot
        wins = s._windows()
        els, ident = snapshot(wins)
        from ..env import win32
        names = {w: win32.window_text(w) for w in wins}
        rows, seen = [], set()
        self.shown = {}
        self.main_hwnd = s.sb.hwnd
        # dialogs and menus first (they are what the next click is usually about), then the ribbon
        order = sorted(els, key=lambda e: (e.root_hwnd == s.sb.hwnd, e.rect.top))
        for e in order:
            ct = _pick_type(e.control_type)
            if (not ct or not e.name or not e.enabled or e.rect.width <= 0 or e.rect.height <= 0
                    or e.name.strip() in NOT_FOR_AGENT):  # window chrome / Backstage: closing the sample ends the demo
                continue
            key = (e.name, ct)
            if key in seen:
                continue
            seen.add(key)
            where = "cửa sổ chính" if e.root_hwnd == s.sb.hwnd else (names.get(e.root_hwnd) or "hộp thoại/menu")
            k = len(rows) + 1
            self.shown[k] = e
            rows.append(f"#{k} {e.name} | {ct} | {where}")
            if len(rows) >= MAX_ELEMENTS:
                break
        state = self._doc_state(s, detail)
        text = (f"Trạng thái file:\n{state}\n\nCửa sổ đang mở: " + ", ".join(names.get(w) or "?" for w in wins)
                + "\n\nControl trên màn hình (#id tên | loại | cửa sổ):\n" + "\n".join(rows))
        try:
            img, (ox, oy) = capture_composite(s.sb.hwnd, wins[1:])
            local = [Rect(left=r.left - ox, top=r.top - oy, right=r.right - ox, bottom=r.bottom - oy) for r in ident]
            img = redact(img, local or [fallback_identity_rect(img.width, s.scale)])
            if img.width > 1400:
                img = img.resize((1400, round(img.height * 1400 / img.width)))
            buf = io.BytesIO()
            img.convert("RGB").save(buf, "PNG", optimize=True)
            url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        except Exception as e:
            log.info("agent.capture_failed", error=repr(e))
            url = ""
        return text, url

    def _doc_state(self, s, detail: bool = False) -> str:
        """A compact view of the document, so the model can tell whether the goal is reached."""
        try:
            if self.app == "excel":
                from ..sandbox.excel import col_letter
                app = s.sb.app
                ws = app.ActiveSheet
                used = ws.UsedRange
                r0, c0 = int(used.Row), int(used.Column)
                nr, nc = min(int(used.Rows.Count), 25), min(int(used.Columns.Count), 12)
                lines = [f"Sheet {ws.Name}, vùng dùng {str(used.Address).replace('$', '')}, đang chọn "
                         f"{str(app.Selection.Address).replace('$', '')}"]
                block = ws.Range(ws.Cells(r0, c0), ws.Cells(r0 + nr - 1, c0 + nc - 1))
                values, formulas = block.Value2, block.Formula  # two COM calls for the whole block
                if not isinstance(values, tuple):
                    values, formulas = ((values,),), ((formulas,),)
                for i, r in enumerate(range(r0, r0 + nr)):
                    cells = []
                    for j, c in enumerate(range(c0, c0 + nc)):
                        v = values[i][j]
                        f = str(formulas[i][j] or "")
                        t = "" if v is None else (f"{v:g}" if isinstance(v, float) else str(v))
                        extra = _cell_flags(ws.Cells(r, c)) if detail else []
                        cells.append(f"{col_letter(c)}{r}={t}" + (f" [{f}]" if f.startswith("=") else "") +
                                     (f" ({','.join(extra)})" if extra else ""))
                    lines.append(" | ".join(cells))
                extras = []
                try:
                    sheets = []
                    for sh in app.ActiveWorkbook.Worksheets:
                        tab = sh.Tab.Color
                        sheets.append(f"{sh.Name}" + (f" (màu tab #{int(tab):06x})" if isinstance(tab, (int, float))
                                                       and tab not in (0, False) else ""))
                    extras.append("Các sheet: " + ", ".join(sheets))
                    if ws.AutoFilterMode:
                        extras.append("đang bật bộ lọc")
                    if int(ws.ChartObjects().Count):
                        extras.append(f"{int(ws.ChartObjects().Count)} biểu đồ")
                    if int(ws.Cells.FormatConditions.Count):
                        extras.append(f"{int(ws.Cells.FormatConditions.Count)} định dạng có điều kiện")
                    if s.sb.app.ActiveWindow.FreezePanes:
                        extras.append("đang cố định ô (freeze panes)")
                except Exception:
                    pass
                return "\n".join(lines + ([", ".join(extras)] if extras else []))
            if self.app == "word":
                d = s.sb.doc
                paras = [f"p{i} [{p.Style.NameLocal}] {str(p.Range.Text).strip()[:120]} ({_word_para_flags(p)})"
                         for i, p in enumerate(d.Paragraphs, 1) if i <= 20]
                return (f"{int(d.Paragraphs.Count)} đoạn, đang chọn: {str(s.sb.app.Selection.Text)[:80]!r}\n"
                        + "\n".join(paras) + "\n" + _word_extras(d))
            d = s.sb.doc
            out = [f"{int(d.Slides.Count)} slide, theme {_safe(lambda: d.SlideMaster.Theme.Name if hasattr(d.SlideMaster, 'Theme') else d.SlideMaster.Name)}"]
            out.append(f"đang ở slide {_safe(lambda: int(s.sb.app.ActiveWindow.View.Slide.SlideIndex))}")
            for i, sl in enumerate(d.Slides, 1):
                texts = [f"s{i}.{k}=" + (repr(str(sh.TextFrame.TextRange.Text)[:60]) or "''")
                         for k, sh in enumerate(sl.Shapes, 1) if sh.HasTextFrame]
                tr = _safe(lambda: int(sl.SlideShowTransition.EntryEffect))
                anim = _safe(lambda: int(sl.TimeLine.MainSequence.Count))
                pics = sum(1 for sh in sl.Shapes if int(sh.Type) in (13, 11))
                out.append(f"slide {i}: layout {sl.Layout}, chuyển trang {tr}, {anim} hiệu ứng động, {pics} ảnh, "
                           + " / ".join(texts))
            return "\n".join(out[:15])
        except Exception as e:
            return f"(không đọc được trạng thái: {e!r})"

    # ---------------------------------------------------------------- deciding
    def _ask(self, system: str, text: str, url: str, schema: type[BaseModel], timeout: float = 40):
        from ..vision.exercise import _gemini, _shape
        content = [{"type": "text", "text": text}]
        if url:
            content.append({"type": "image_url", "image_url": {"url": url}})
        for attempt in range(2):  # a cut-off or malformed answer gets one more try
            self.calls += 1
            raw = _gemini([{"role": "system", "content": system + " Trả về đúng một object JSON dạng "
                            + _shape(schema.model_json_schema()) + " (thought tối đa 25 từ)."},
                           {"role": "user", "content": content}], timeout, 3000)
            if raw is None:
                raise AgentUnavailable("Gemini không trả lời")
            for candidate in (raw, *(m.group(0) for m in [re.search(r"\{.*\}", raw, re.S)] if m)):
                try:
                    return schema.model_validate_json(candidate)
                except ValidationError:
                    continue
            log.info("agent.bad_answer", attempt=attempt, raw=raw[:200])
        return None

    def decide(self, s) -> Decision:
        t0 = time.monotonic()
        text, url = self.observe(s)
        t1 = time.monotonic()
        done = "\n".join(f"{i}. {h['what']} → {h['result']}" for i, h in enumerate(self.history, 1)) or "(chưa có)"
        prompt = f"Mục tiêu: {self.goal}\n\nĐã làm:\n{done}\n\n{text}"
        d = self._ask(SYSTEM.format(app={"excel": "Excel", "word": "Word", "powerpoint": "PowerPoint"}[self.app],
                                    tips=TIPS.get(self.app, "")),
                      prompt, url, Decision) or Decision(action="invalid", thought="câu trả lời của model không hợp lệ")
        log.info("agent.decide", action=d.action, name=d.name, cell=d.cell, value=d.value[:60], thought=d.thought[:60],
                 look_s=round(t1 - t0, 1), model_s=round(time.monotonic() - t1, 1), chars=len(prompt))
        return d

    def to_step(self, d: Decision, n: int) -> Step | None:
        a = d.action.strip().lower()
        el = self.shown.get(d.id) if d.id else None
        if el is None and d.name:  # no id: the first listed control with that name (and type)
            el = next((e for e in self.shown.values() if e.name == d.name
                       and (not d.control_type or e.control_type == d.control_type)), None)
        if el is not None and a in ("click", "set_value"):
            d.name, d.control_type = el.name, el.control_type
        aid = (el.automation_id or None) if el is not None else None
        if a == "keys" and not d.value and "+" in d.name:
            d.value = d.name
        if a == "keys" and re.match(r"^\s*alt\s*[,+ ]\s*[a-z0-9]\s*([, ]|$)", d.value or "", re.I):
            return None  # KeyTips sequences put letters all over the screenshots; the model is told to click
        if a == "click" and d.name:
            ct = d.control_type or "Button"
            intent = {"TabItem": "select_ribbon_tab", "ListItem": "select_item", "CheckBox": "toggle",
                      "RadioButton": "select_item"}.get(ct, "invoke")
            if d.expect == "menu" and intent == "invoke" and ct in ("MenuItem", "SplitButton", "Button", "ComboBox"):
                intent = "expand"
            exp = {"tab": "tab_selected", "menu": "expanded", "dialog": "dialog_opened"}.get(d.expect, "none")
            if exp == "expanded" and intent != "expand":
                exp = "none"
            if intent == "select_ribbon_tab":
                exp = "tab_selected"
            return Step(id=n, intent=intent, target=Target(names=[d.name], control_type=ct, automation_id=aid),
                        expected=Expected(type=exp), capture_result=d.expect == "dialog")
        if a == "type" and self.app == "excel" and d.cell and d.value:
            first = d.cell.split(":")[0]
            exp = (Expected(type="com_check", prop="cell.formula_ok", ref=first, op="true") if d.value.startswith("=")
                   else Expected(type="none"))
            return Step(id=n, intent="type_formula", value=d.value, target=Target(names=[d.cell], control_type="Cell"),
                        expected=exp, capture_result=True)
        if a == "type" and self.app != "excel" and d.value:
            target = Target(names=[d.cell], control_type="Cell") if d.cell else None
            return Step(id=n, intent="type_text", value=d.value, target=target, expected=Expected(type="none"),
                        capture_result=True)
        if (a == "keys" and d.value and self.app == "excel" and not d.cell
                and d.value.replace(" ", "").lower() not in GLOBAL_KEYS):
            self.reject = "phím tắt trong Excel phải kèm cell (ô/vùng cần chọn trước khi nhấn)"
            return None
        if a == "keys" and d.value:
            # "select D1 then Ctrl+Space": the cell is selected first, or the keys hit whatever was selected
            target = Target(names=[d.cell], control_type="Cell") if d.cell else None
            return Step(id=n, intent="key_combo", value=d.value, target=target, expected=Expected(type="none"),
                        capture_result=True)
        if a == "select" and d.cell:
            return Step(id=n, intent="select_range", target=Target(names=[d.cell], control_type="Cell"))
        if a == "set_value" and d.name and d.value:
            value = d.value
            if el is not None and (el.control_type == "ComboBox" or el.root_hwnd == self.main_hwnd):
                # Font Size and friends, on the ribbon or in a collapsed group's popup: type and press Enter
                value = value.rstrip("\n") + "\n"
            elif el is not None and el.root_hwnd != self.main_hwnd:
                value = value.rstrip("\t") + "\t"  # dialog box: type and Tab out, as a person does
            return Step(id=n, intent="set_value", value=value,
                        target=Target(names=[d.name], control_type=d.control_type or "Edit", automation_id=aid))
        return None

    def describe(self, d: Decision) -> str:
        a = d.action
        if a == "click":
            return f"bấm {d.name} ({d.control_type})"
        if a == "type":
            return f"gõ {d.value} vào {d.cell}"
        if a == "keys":
            return f"nhấn {d.value}"
        if a == "select":
            return f"chọn {d.cell}"
        if a == "set_value":
            return f"nhập {d.value!r} vào {d.name}"
        return a

    @staticmethod
    def change_note(before: str, after: str) -> str:
        """'file thay đổi: …' for the history line: the first lines that differ, so the model sees the effect."""
        if before == after:
            return "file không thay đổi"
        b, a = before.splitlines(), after.splitlines()
        diff = [ln for ln in a if ln not in b][:3]
        return "file thay đổi: " + " || ".join(x[:160] for x in diff) if diff else "file thay đổi"

    def judge(self, s) -> Verdict:
        time.sleep(0.6)  # let Office repaint after the last click
        text, url = self.observe(s, detail=True)
        try:
            before = f"Trạng thái BAN ĐẦU (trước khi làm):\n{self.initial_state}\n\n" if self.initial_state else ""
            v = self._ask(VERDICT, f"Mục tiêu: {self.goal}\n\n{before}Trạng thái CUỐI và màn hình:\n{text}", url,
                          Verdict, timeout=40)
            if v is None:
                raise ValueError("verdict không hợp lệ")
        except Exception as e:
            log.info("agent.judge_failed", error=repr(e))
            v = Verdict(achieved=not self.gave_up, reason="không kiểm tra được kết quả cuối")
        self.verdict = v
        log.info("agent.verdict", achieved=v.achieved, reason=v.reason)
        return v


class AgentUnavailable(Exception):
    pass


def self_knowledge_path(app: str):
    """Cards the agent learned on this machine: next to the user's data, not inside the (read-only) install."""
    import os
    from pathlib import Path
    root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Kem" / "knowledge"
    return root / f"{app}.self.yaml"


def save_self_card(app: str, card: dict) -> None:
    import yaml
    path = self_knowledge_path(app)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    data = data or {"cards": []}
    data["cards"] = [c for c in data["cards"] if c.get("id") != card["id"]] + [card]
    path.write_text("# Learned by Guider's observe-act agent on this machine (ADR-0007).\n"
                    + yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def card_from_trace(goal: str, app: str, trace, fixture_id: str | None) -> dict | None:
    """The path the agent found, as a card: only the steps that worked, in order (ADR-0007: learn by doing)."""
    from ..intent.knowledge import fold
    steps = []
    for st in trace.steps:
        if not st.verified:
            continue
        step = {"id": len(steps) + 1, "intent": st.intent}
        if st.intent in ("key_combo", "type_text"):
            step["value"] = st.value
        elif st.intent in ("type_formula", "select_range"):
            step["target"] = {"names": [st.element_name], "control_type": "Cell"}
            if st.value:
                step["value"] = st.value
        else:
            step["target"] = {"names": [st.element_name], "control_type": st.control_type or "Button"}
            if st.value:
                step["value"] = st.value
        steps.append(step)
    if not steps:
        return None
    slug = re.sub(r"[^a-z0-9]+", "_", fold(goal))[:48].strip("_") or "task"
    title = goal.strip()
    if not fold(title).startswith("cach"):
        title = "Cách " + title[:1].lower() + title[1:]
    return {"id": f"agent_{slug}", "title": title[:120], "keywords": [goal.strip()[:80]],
            "fixture_id": fixture_id, "steps": steps,
            "learned": {"source": "agent", "when": time.strftime("%d/%m/%Y")}}
