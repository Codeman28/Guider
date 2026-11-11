"""Exercise mode (ADR-0006): the pictured table is rebuilt as it is, and the plan is written for that table."""
from __future__ import annotations

import pytest

from kem_engine.vision import exercise as ex

PICTURE = """Cột / Hàng | A (STT) | B (Mã NV) | C (Họ tên) | D (Chức vụ) | E (Ngày công) | F (Lương CB) | G (Doanh số)
2 | 1 | KD001 | Nguyễn Văn A | Sale | 26 | 7000000 | 55000
3 | 2 | KT002 | Trần Thị B | Kế toán | 24 | 8000000 | 0
"""


def test_row_number_column_and_letter_prefixes_are_dropped():
    fx = ex.table_fixture(PICTURE)
    assert fx["columns"] == ["STT", "Mã NV", "Họ tên", "Chức vụ", "Ngày công", "Lương CB", "Doanh số"]
    assert fx["rows"][0] == [1, "KD001", "Nguyễn Văn A", "Sale", 26, 7000000, 55000]
    assert fx["refs"] == "exact"


def test_plain_table_is_kept_as_is():
    fx = ex.table_fixture("Mã | Số lượng\nSP01 | 3\nSP02 | 012\n")
    assert fx["columns"] == ["Mã", "Số lượng"] and fx["rows"] == [["SP01", 3], ["SP02", "012"]]
    assert ex.table_fixture("không có bảng") is None


def test_grid_text_names_cells_the_way_excel_does():
    g = ex.grid_text(ex.table_fixture(PICTURE)).splitlines()
    assert g[0].startswith("Hàng | A | B | C") and g[1].startswith("1 | STT") and g[2].startswith("2 | 1 | KD001")


def test_plan_types_headers_then_fills_ranges():
    sol = ex.Solution(steps=[ex.SolStep(task="Lương", header_cell="H1", header_text="Lương thực nhận", range="H2:H3",
                                        formula="=F2/26*E2", explain="Lương CB / 26 × ngày công"),
                             ex.SolStep(task="Tổng", range="G4", formula="=SUM(G2:G3)", explain="cộng cột G")],
                      unsolved=["Vẽ biểu đồ"])
    plan = ex.to_plan(ex.table_fixture(PICTURE), sol, "Giải bài tập")
    assert [(s.intent, s.target.names[0], s.value) for s in plan.steps] == [
        ("type_formula", "H1", "Lương thực nhận"), ("type_formula", "H2:H3", "=F2/26*E2"),
        ("type_formula", "G4", "=SUM(G2:G3)")]
    assert plan.steps[1].expected.ref == "H2" and plan.steps[1].expected.prop == "cell.formula_ok"
    assert "Ctrl+Enter" in plan.example and "Vẽ biểu đồ" in plan.example


class FakeRange:
    def __init__(self, ws, ref):
        self.ws, self.ref = ws, ref
        col, row = ref.split(":")[0][0], int(ref.split(":")[0][1:])
        self.Row, self.Column = row, ord(col) - 64
        me = self

        class Cells(list):
            def __call__(self, r, c):
                return me

        self.Cells = Cells([self])
        self.Address = ref

    @property
    def Formula2(self):
        return self.ws.formulas.get(self.ref)

    @Formula2.setter
    def Formula2(self, v):
        self.ws.formulas[self.ref] = v

    @property
    def Text(self):
        return "#DIV/0!" if "/0" in self.ws.formulas.get(self.ref, "") else "42"


def test_solution_may_not_overwrite_the_table(monkeypatch):
    class WS:
        formulas: dict = {}
        CircularReference = None

        class _Cells:
            def Clear(self):
                pass

            def __call__(self, r, c):
                class Spare:
                    def ClearContents(self):
                        pass
                return Spare()

        Cells = _Cells()

        def Range(self, ref):
            return FakeRange(self, ref)

    class Lab:
        class app:
            @staticmethod
            def Calculate():
                pass

        class wb:
            @staticmethod
            def Worksheets(i):
                return WS()

    monkeypatch.setattr("kem_engine.sandbox.excel.fill_sheet", lambda ws, fx: None)
    fx = ex.table_fixture(PICTURE)
    over = ex.Solution(steps=[ex.SolStep(task="x", range="E2", formula="=1", explain="")])
    ok, notes = ex._sheet_ok(Lab, fx, over)
    assert not ok and "ghi đè" in notes[0]
    bad = ex.Solution(steps=[ex.SolStep(task="x", range="H2", formula="F2/0", explain="")])
    ok, notes = ex._sheet_ok(Lab, fx, bad)
    assert not ok and "lỗi" in notes[0] and bad.steps[0].formula == "=F2/0"


def test_no_tasks_asks_for_the_question(tmp_path, monkeypatch):
    from PIL import Image
    img = tmp_path / "p.png"
    Image.new("RGB", (60, 40), "white").save(img)
    monkeypatch.setattr(ex, "_vision", lambda *a, **k: '{"app": "excel", "content": "A | B\\n1 | 2", "tasks": []}')
    with pytest.raises(ex.ExerciseError, match="đề bài"):
        ex.read_and_solve(img, "", tmp_path / "w")


def test_blank_row_between_groups_stays_in_place():
    fx = ex.table_fixture("Mục | Vật dụng | Số lượng\nA | Bút | 1\n | | \nB | Vở | 2\n | | \n")
    assert fx["rows"] == [["A", "Bút", 1], ["", "", ""], ["B", "Vở", 2]]


def test_non_formula_tasks_become_demonstrable_steps():
    sol = ex.Solution(actions=[
        ex.SolAction(task="Tô màu hàng bắt buộc", kind="highlight_rows", range="A2:F27", formula='=$D2="Bắt buộc"'),
        ex.SolAction(task="Lọc", kind="filter", range="A1:F27"),
        ex.SolAction(task="Sắp xếp", kind="sort_desc", range="A1:F27", column="F2"),
        ex.SolAction(task="In đậm tiêu đề", kind="bold", range="A1:F1")])
    plan = ex.to_plan(ex.table_fixture("A | B\n1 | 2"), sol, "t")
    sels = [s.target.names[0] for s in plan.steps if s.intent == "select_range"]
    assert sels == ["A2:F27", "A1:F27", "F2", "A1:F1"]
    assert any(s.intent == "set_value" and s.value == '=$D2="Bắt buộc"' for s in plan.steps)
    assert [s.id for s in plan.steps] == list(range(1, len(plan.steps) + 1))
    assert "Conditional Formatting" in plan.example and "Ctrl+B" in plan.example


def test_filter_and_highlight_cover_the_whole_table():
    fx = ex.table_fixture("A | B | C\n" + "\n".join(f"{i} | x | y" for i in range(26)))  # rows 2..27
    sol = ex.Solution(actions=[ex.SolAction(task="l", kind="filter", range="A1:C26"),
                               ex.SolAction(task="t", kind="highlight_rows", range="A2:C26", formula='=$B2="x"'),
                               ex.SolAction(task="s", kind="sort_desc", range="A1:C10", column="C2")])
    ex.fit_actions(fx, sol)
    assert [a.range for a in sol.actions] == ["A1:C27", "A2:C27", "A1:C27"]
    assert sol.actions[1].formula == '=$B2="x"'


def test_answer_nested_under_an_echoed_schema_is_still_read():
    raw = ('{"properties": {"app": {"type": "string"}, "content": {"type": "string"}}, '
           '"answer": {"app": "excel", "content": "A | B\\n1 | 2", "tasks": ["Tính tổng"]}}')
    seen = ex.parse_seen(raw)
    assert seen.content == "A | B\n1 | 2" and seen.tasks == ["Tính tổng"]
    assert ex._shape(ex.SeenExercise.model_json_schema()).startswith('{"app": "..."')


def test_single_results_below_the_table_get_a_label():
    fx = ex.table_fixture("A | B | C\n1 | x | 3\n2 | y | 4")  # table A1:C3
    sol = ex.Solution(steps=[ex.SolStep(task="Tổng số lượng", range="C5", formula="=SUM(C2:C3)", explain=""),
                             ex.SolStep(task="Đếm", range="A6", formula="=COUNTA(A2:A3)", explain="")])
    ex.label_results(fx, sol)
    assert (sol.steps[0].header_cell, sol.steps[0].header_text) == ("B5", "Tổng số lượng")
    assert (sol.steps[1].header_cell, sol.steps[1].header_text) == ("B6", "Đếm")


def test_a_header_in_row_one_for_a_single_total_moves_next_to_it():
    fx = ex.table_fixture("A | B | C\n1 | x | 3\n2 | y | 4")
    sol = ex.Solution(steps=[ex.SolStep(task="Tổng", header_cell="D1", header_text="Tổng SL", range="C5",
                                        formula="=SUM(C2:C3)", explain="")])
    ex.label_results(fx, sol)
    assert (sol.steps[0].header_cell, sol.steps[0].header_text) == ("B5", "Tổng SL")
