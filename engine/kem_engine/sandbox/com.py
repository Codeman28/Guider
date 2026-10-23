"""COM call helpers. Office answers RPC_E_SERVERCALL_RETRYLATER while busy or in cell-edit mode (S4)."""
from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")

RPC_E_SERVERCALL_RETRYLATER = -2147417846
RPC_E_CALL_REJECTED = -2147418111
DISP_E_EXCEPTION = -2147352567
XL_E_NOT_READY = -2146777998  # 0x800AC472: Excel not ready (eval run 4: writing the fixture right after Add)


def is_busy_error(e: BaseException) -> bool:
    code = getattr(e, "hresult", None)
    if code is None and getattr(e, "args", None):
        code = e.args[0] if isinstance(e.args[0], int) else None
    if code in (RPC_E_SERVERCALL_RETRYLATER, RPC_E_CALL_REJECTED):
        return True
    # DISP_E_EXCEPTION carries Excel's own code in excepinfo[5]
    if code == DISP_E_EXCEPTION and len(e.args) > 2 and isinstance(e.args[2], tuple) and len(e.args[2]) > 5:
        return e.args[2][5] == XL_E_NOT_READY
    return False


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
