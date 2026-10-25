"""PowerPoint sandbox. Spike S2: PowerPoint is single-instance and exposes no HWND over COM.
Guider therefore only demonstrates when PowerPoint is not already running (office.setup refuses),
and finds the frame by the new presentation's caption."""
from __future__ import annotations

import time

from ..env import win32
from . import office

PP_LAYOUT_TITLE, PP_LAYOUT_TEXT = 1, 2  # PpSlideLayout.ppLayoutTitle / ppLayoutText


def _hwnd(app, doc) -> int:
    title = str(doc.Name).rsplit(".", 1)[0]  # a user's file shows its name with or without extension
    for _ in range(40):
        for h in win32.top_level_windows():
            if win32.class_name(h) == "PPTFrameClass" and win32.window_text(h).startswith(title):
                return h
        time.sleep(0.25)
    raise RuntimeError(f"PowerPoint frame for {title!r} not found")


def _fill(doc, fx: dict) -> None:
    """fixture: {"slides": [{"title": "...", "body": ["...", ...]}, ...]}. Synthetic text only."""
    for i, sl in enumerate(fx["slides"], start=1):
        layout = PP_LAYOUT_TEXT if sl.get("body") else PP_LAYOUT_TITLE
        slide = doc.Slides.Add(i, layout)
        slide.Shapes(1).TextFrame.TextRange.Text = sl["title"]
        if sl.get("body"):
            slide.Shapes(2).TextFrame.TextRange.Text = "\r".join(sl["body"])
    doc.Windows(1).View.GotoSlide(1)


def _select(doc, ref: str) -> None:
    """ref: "s<N>" (slide N in the thumbnail pane) or "s<N>.<M>" (shape M's text on slide N)."""
    slide_no, _, shape_no = ref[1:].partition(".")
    win = doc.Windows(1)
    win.View.GotoSlide(int(slide_no))
    if shape_no:
        doc.Slides(int(slide_no)).Shapes(int(shape_no)).TextFrame.TextRange.Select()
    else:
        doc.Slides(int(slide_no)).Select()


def _close(doc) -> None:
    doc.Saved = True  # never prompt, never save
    doc.Close()


def _open(app, path: str):
    return app.Presentations.Open(path, ReadOnly=0, Untitled=0, WithWindow=-1)


def _map_ref(doc, ref: str) -> str:
    """Slide refs clamped to the user's deck; "sN.M" falls back to the first shape on that slide with text."""
    slide_no, _, shape_no = ref[1:].partition(".")
    n = max(1, min(int(slide_no), int(doc.Slides.Count)))
    if not shape_no:
        return f"s{n}"
    shapes = doc.Slides(n).Shapes
    m = int(shape_no)
    if m <= shapes.Count and shapes(m).HasTextFrame and shapes(m).TextFrame.HasText:
        return f"s{n}.{m}"
    for i in range(1, shapes.Count + 1):
        if shapes(i).HasTextFrame and shapes(i).TextFrame.HasText:
            return f"s{n}.{i}"
    return f"s{n}"


SPEC = office.AppSpec(
    name="PowerPoint",
    progid="PowerPoint.Application",
    frame_class="PPTFrameClass",
    dialog_classes=("NUIDialog", "#32770"),
    edit_child_class="paneClassDC",
    single_instance=True,
    add_doc=lambda app: app.Presentations.Add(True),
    doc_hwnd=_hwnd,
    fill=_fill,
    select=_select,
    close_doc=_close,
    doc_count=lambda app: app.Presentations.Count,
    ping=lambda app: app.Presentations.Count,
    open_doc=_open,
    map_ref=_map_ref,
    deselect=lambda doc: doc.Windows(1).Selection.Unselect(),
)
