"""Verifier (SPEC §6.9): post-conditions read back from UIA or COM. Closed set — nothing is eval'd."""
from __future__ import annotations

import time
from typing import Any, Callable

from ..sandbox.com import com_retry

DEFAULT_TIMEOUT = 5.0
POLL = 0.1


def poll(check: Callable[[], bool], timeout: float = DEFAULT_TIMEOUT, interval: float = POLL) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            if check():
                return True
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def _sum_sheets(doc, per_sheet: Callable[[object], int]) -> int:
    n = com_retry(lambda: doc.Worksheets.Count)
    return sum(com_retry(lambda i=i: per_sheet(doc.Worksheets(i))) for i in range(1, n + 1))


def pivot_tables(doc) -> int:
    return _sum_sheets(doc, lambda ws: ws.PivotTables().Count)


def charts(doc) -> int:
    return _sum_sheets(doc, lambda ws: ws.ChartObjects().Count)


def format_conditions(doc) -> int:
    return _sum_sheets(doc, lambda ws: ws.Cells.FormatConditions.Count)


COM_COUNTERS: dict[str, Callable[[object], int]] = {
    "com_pivot_tables": pivot_tables,
    "com_charts": charts,
    "com_format_conditions": format_conditions,
}


def _first_sheet(doc):
    return doc.Worksheets(1)


def _range(doc, ref: str):
    return _first_sheet(doc).Range(ref)


def _window(doc):
    return doc.Windows(1)


def _sorted_desc(doc, ref: str) -> bool:
    vals = [r[0] for r in _range(doc, ref).Value]
    return vals == sorted(vals, reverse=True)


# name → getter(doc, ref). Every readable property is listed here; plans can only name these keys.
COM_PROPS: dict[str, Callable[[Any, str | None], Any]] = {
    "range.font.bold": lambda d, r: _range(d, r).Font.Bold,
    "range.font.italic": lambda d, r: _range(d, r).Font.Italic,
    "range.font.color": lambda d, r: int(_range(d, r).Font.Color),
    "range.font.size": lambda d, r: float(_range(d, r).Font.Size),
    # a typed formula landed: the cell holds a formula and does not show an error (#NAME?, #VALUE!, …)
    "cell.formula_ok": lambda d, r: bool(_range(d, r).HasFormula) and not str(_range(d, r).Text).startswith("#"),
    "cell.value": lambda d, r: _range(d, r).Value,
    "range.interior.color": lambda d, r: int(_range(d, r).Interior.Color),
    # the colour actually shown, conditional formatting included (Interior.Color ignores CF)
    "range.display_color": lambda d, r: int(_range(d, r).DisplayFormat.Interior.Color),
    "range.wrap_text": lambda d, r: _range(d, r).WrapText,
    "range.merge_cells": lambda d, r: _range(d, r).MergeCells,
    "range.horizontal_alignment": lambda d, r: int(_range(d, r).HorizontalAlignment),
    "range.number_format": lambda d, r: str(_range(d, r).NumberFormat),
    "range.sorted_desc": lambda d, r: _sorted_desc(d, r),
    "sheet.autofilter": lambda d, r: bool(_first_sheet(d).AutoFilterMode),
    "sheet.list_objects": lambda d, r: int(_first_sheet(d).ListObjects.Count),
    "sheet.page_orientation": lambda d, r: int(_first_sheet(d).PageSetup.Orientation),
    "window.freeze_panes": lambda d, r: bool(_window(d).FreezePanes),
    "window.display_gridlines": lambda d, r: bool(_window(d).DisplayGridlines),
    "window.display_formulas": lambda d, r: bool(_window(d).DisplayFormulas),
    "book.pivot_tables": lambda d, r: pivot_tables(d),
    "book.charts": lambda d, r: charts(d),
    "book.format_conditions": lambda d, r: format_conditions(d),
    # Word (doc = Document; ref = paragraph number)
    "word.par.font.bold": lambda d, r: d.Paragraphs(int(r)).Range.Font.Bold,
    "word.par.font.size": lambda d, r: float(d.Paragraphs(int(r)).Range.Font.Size),
    "word.par.font.italic": lambda d, r: d.Paragraphs(int(r)).Range.Font.Italic,
    "word.par.font.underline": lambda d, r: int(d.Paragraphs(int(r)).Range.Font.Underline),
    "word.par.font.color": lambda d, r: int(d.Paragraphs(int(r)).Range.Font.Color),
    "word.par.highlight": lambda d, r: int(d.Paragraphs(int(r)).Range.HighlightColorIndex),
    "word.par.alignment": lambda d, r: int(d.Paragraphs(int(r)).Alignment),  # 1 = centred
    "word.par.style": lambda d, r: str(d.Paragraphs(int(r)).Style.NameLocal),
    "word.par.list": lambda d, r: int(d.Paragraphs(int(r)).Range.ListFormat.ListType),  # 0 = none
    "word.tables": lambda d, r: int(d.Tables.Count),
    "word.page.orientation": lambda d, r: int(d.PageSetup.Orientation),  # 1 = landscape
    "word.toc": lambda d, r: int(d.TablesOfContents.Count),
    "word.page_numbers": lambda d, r: int(d.Sections(1).Footers(1).PageNumbers.Count)
    + int(d.Sections(1).Headers(1).PageNumbers.Count),
    "word.pages": lambda d, r: int(d.ComputeStatistics(2)),  # wdStatisticPages
    "word.par.font.strike": lambda d, r: int(d.Paragraphs(int(r)).Range.Font.StrikeThrough),
    "word.page.columns": lambda d, r: int(d.PageSetup.TextColumns.Count),
    "word.page.left_margin": lambda d, r: round(float(d.PageSetup.LeftMargin)),  # points; Narrow = 36
    # PowerPoint (doc = Presentation; ref = slide number, or "slide.shape")
    "ppt.slides": lambda d, r: int(d.Slides.Count),
    "ppt.slide.shapes": lambda d, r: int(d.Slides(int(r)).Shapes.Count),
    "ppt.slide.transition": lambda d, r: int(d.Slides(int(r)).SlideShowTransition.EntryEffect),  # 0 = none
    "ppt.slide.animations": lambda d, r: int(d.Slides(int(r)).TimeLine.MainSequence.Count),
    "ppt.shape.font.bold": lambda d, r: int(_ppt_shape(d, r).TextFrame.TextRange.Font.Bold),
    "ppt.shape.font.size": lambda d, r: float(_ppt_shape(d, r).TextFrame.TextRange.Font.Size),
    "ppt.shape.font.italic": lambda d, r: int(_ppt_shape(d, r).TextFrame.TextRange.Font.Italic),
    "ppt.shape.font.underline": lambda d, r: int(_ppt_shape(d, r).TextFrame.TextRange.Font.Underline),
    "ppt.shape.bullet_type": lambda d, r: int(_ppt_shape(d, r).TextFrame.TextRange.ParagraphFormat.Bullet.Type),  # 2 = numbered
    "ppt.shape.alignment": lambda d, r: int(_ppt_shape(d, r).TextFrame.TextRange.ParagraphFormat.Alignment),
    "ppt.slide.has_picture_or_chart": lambda d, r: any(int(s.Type) in (3, 13) for s in d.Slides(int(r)).Shapes),
    "ppt.shape.font.strike": lambda d, r: int(_ppt_shape(d, r).TextFrame2.TextRange.Font.Strike),  # 0 = none
    "ppt.slide.layout": lambda d, r: int(d.Slides(int(r)).Layout),  # 11 = ppLayoutTitleOnly
    "ppt.slide.hidden": lambda d, r: int(d.Slides(int(r)).SlideShowTransition.Hidden),
}


def _ppt_shape(doc, ref: str):
    slide, _, shape = str(ref).partition(".")
    return doc.Slides(int(slide)).Shapes(int(shape))


def compare(actual: Any, op: str, value: Any) -> bool:
    if op == "true":
        return actual is True or actual == -1 or actual == 1
    if op == "false":
        return actual is False or actual == 0
    if op == "contains":
        return str(value) in str(actual)
    if op == "gte":
        return actual is not None and float(actual) >= float(value)
    return actual == value


def com_check(doc, prop: str, ref: str | None, op: str, value: Any) -> bool:
    getter = COM_PROPS.get(prop)
    if getter is None:
        raise KeyError(f"unknown COM check {prop!r}")
    return compare(com_retry(lambda: getter(doc, ref)), op, value)
