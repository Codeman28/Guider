"""Verifier (SPEC §6.9): post-conditions read back from UIA or COM. Closed set — nothing is eval'd."""
from __future__ import annotations

import time
from typing import Callable

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
