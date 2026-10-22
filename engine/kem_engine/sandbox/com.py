"""COM call helpers. Office answers RPC_E_SERVERCALL_RETRYLATER while busy or in cell-edit mode (S4)."""
from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")

RPC_E_SERVERCALL_RETRYLATER = -2147417846
RPC_E_CALL_REJECTED = -2147418111


def is_busy_error(e: BaseException) -> bool:
    code = getattr(e, "hresult", None)
    if code is None and getattr(e, "args", None):
        code = e.args[0] if isinstance(e.args[0], int) else None
    return code in (RPC_E_SERVERCALL_RETRYLATER, RPC_E_CALL_REJECTED)


def com_retry(fn: Callable[[], T], timeout: float = 5.0, interval: float = 0.2,
              on_busy: Callable[[], None] | None = None) -> T:
    """Call fn, retrying while Office reports it is busy. on_busy runs once before the first retry."""
    deadline = time.monotonic() + timeout
    nudged = False
    while True:
        try:
            return fn()
        except Exception as e:
            if not is_busy_error(e) or time.monotonic() >= deadline:
                raise
            if on_busy and not nudged:
                on_busy()
                nudged = True
            time.sleep(interval)
