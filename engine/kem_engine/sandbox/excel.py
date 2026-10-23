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
)


def setup(fixture_id: str | None, size_logical=(1280, 800), pos=(40, 40), timeout: float = 60.0) -> SandboxHandle:
    return office.setup(SPEC, fixture_id, size_logical, pos, timeout)


sandbox_windows = office.sandbox_windows
dialogs = office.dialogs
unstick = office.unstick
teardown = office.teardown
