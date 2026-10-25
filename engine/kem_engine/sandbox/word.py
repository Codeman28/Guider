"""Word sandbox: own process per DispatchEx (spike S2), HWND = Document.ActiveWindow.Hwnd."""
from __future__ import annotations

from . import office

WD_DO_NOT_SAVE = 0  # WdSaveOptions.wdDoNotSaveChanges
WD_STYLE_HEADING_1 = -2  # WdBuiltinStyle.wdStyleHeading1


def _fill(doc, fx: dict) -> None:
    """fixture: {"paragraphs": ["Tiêu đề", "đoạn 1", ...], "headings": [2, 4]}. Synthetic text only (SPEC §6.3)."""
    doc.Content.Text = "\r".join(fx["paragraphs"])
    for n in fx.get("headings", []):  # built-in Heading 1 by id, so it works in any UI language
        doc.Paragraphs(n).Style = WD_STYLE_HEADING_1
    doc.Range(0, 0).Select()


def _select(doc, ref: str) -> None:
    """ref: "all", "p<N>" (paragraph N), or "p<A>-p<B>"."""
    if ref == "all":
        doc.Content.Select()
        return
    a, _, b = ref.partition("-")
    start = doc.Paragraphs(int(a[1:])).Range.Start
    end = doc.Paragraphs(int((b or a)[1:])).Range.End
    doc.Range(start, end).Select()


def _open(app, path: str):
    app.DisplayAlerts = 0
    return app.Documents.Open(path, ConfirmConversions=False, ReadOnly=False, AddToRecentFiles=False,
                              Visible=True)


def _map_ref(doc, ref: str) -> str:
    """Paragraph refs of the fixture → the same numbers clamped to the user's document."""
    if ref == "all":
        return ref
    n = int(doc.Paragraphs.Count)
    a, _, b = ref.partition("-")
    pa = min(int(a[1:]), n)
    return f"p{pa}" if not b else f"p{pa}-p{max(pa, min(int(b[1:]), n))}"


SPEC = office.AppSpec(
    name="Word",
    progid="Word.Application",
    frame_class="OpusApp",
    dialog_classes=("NUIDialog", "bosa_sdm_msword", "#32770"),
    edit_child_class="_WwG",
    single_instance=False,
    add_doc=lambda app: (setattr(app, "DisplayAlerts", 0), app.Documents.Add())[1],
    doc_hwnd=lambda app, doc: doc.ActiveWindow.Hwnd,
    fill=_fill,
    select=_select,
    close_doc=lambda doc: doc.Close(SaveChanges=WD_DO_NOT_SAVE),
    doc_count=lambda app: app.Documents.Count,
    ping=lambda app: app.Documents.Count,
    open_doc=_open,
    map_ref=_map_ref,
)
