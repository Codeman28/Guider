"""Excel sandbox (SPEC §6.3): a private instance with one blank, never-saved workbook (S2: own process)."""
from __future__ import annotations

from . import office
from .office import SandboxHandle, SandboxRefused, load_fixture  # noqa: F401  (re-exported)


def _fill(doc, fx: dict) -> None:
    rows = [fx["columns"]] + fx["rows"]
    ws = doc.Worksheets(1)
    ref = f"A1:{chr(ord('A') + len(fx['columns']) - 1)}{len(rows)}"
    ws.Range(ref).Value = rows
    ws.Range("A1").Select()


def _open(app, path: str):
    app.DisplayAlerts = False
    return app.Workbooks.Open(path, UpdateLinks=0, ReadOnly=False, AddToMru=False)


def _map_ref(doc, ref: str) -> str:
    """Cards select fixture ranges (A1:D21 = the table, D2 = a value cell). In the user's file: the used
    range of the active sheet, or its first cell in the last column below the header."""
    used = doc.ActiveSheet.UsedRange
    if ":" in ref:
        return str(used.Address)
    rows, cols = int(used.Rows.Count), int(used.Columns.Count)
    return str(used.Cells(2 if rows > 1 else 1, cols).Address)


def _deselect(doc) -> None:
    """Select one empty cell just outside the data, so the result (colours, borders, a chart) is not
    hidden under the selection shading."""
    ws = doc.Application.ActiveSheet
    used = ws.UsedRange
    ws.Cells(int(used.Row) + int(used.Rows.Count) + 1, int(used.Column) + int(used.Columns.Count) + 1).Select()


SPEC = office.AppSpec(
    name="Excel",
    progid="Excel.Application",
    frame_class="XLMAIN",
    dialog_classes=("NUIDialog", "bosa_sdm_XL9", "#32770"),
    edit_child_class="EXCEL7",
    single_instance=False,
    add_doc=lambda app: (setattr(app, "DisplayAlerts", False), app.Workbooks.Add())[1],
    doc_hwnd=lambda app, doc: app.Hwnd,
    fill=_fill,
    select=lambda doc, ref: doc.ActiveSheet.Range(ref).Select(),
    close_doc=lambda doc: doc.Close(SaveChanges=False),
    doc_count=lambda app: app.Workbooks.Count,
    ping=lambda app: app.Ready,
    open_doc=_open,
    map_ref=_map_ref,
    deselect=_deselect,
)


def setup(fixture_id: str | None, size_logical=(1280, 800), pos=(40, 40), timeout: float = 60.0) -> SandboxHandle:
    return office.setup(SPEC, fixture_id, size_logical, pos, timeout)


sandbox_windows = office.sandbox_windows
dialogs = office.dialogs
unstick = office.unstick
teardown = office.teardown
