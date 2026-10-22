"""S2: Does DispatchEx give Excel/Word/PowerPoint a private process? How do we get the sandbox HWND?

Opens two sandboxes per app (sequentially overlapping) and records PIDs/HWNDs.
"""
import sys
import time

from _common import (APPS, close_sandbox, office_pids, open_sandbox, save_json,
                     set_dpi_awareness, top_level_windows, class_name, window_pid)

set_dpi_awareness()

results = {}
for name in (sys.argv[1:] or list(APPS)):
    exe = APPS[name][1]
    r = {"pre_existing_pids": sorted(office_pids(exe))}
    a = b = None
    try:
        t0 = time.perf_counter()
        a = open_sandbox(name)
        r["open_a_s"] = round(time.perf_counter() - t0, 2)
        b = open_sandbox(name, pos=(120, 120))
        r["a"] = {"hwnd": a.hwnd, "pid": a.pid, "class": class_name(a.hwnd), "created_instance": a.created_instance}
        r["b"] = {"hwnd": b.hwnd, "pid": b.pid, "class": class_name(b.hwnd), "created_instance": b.created_instance}
        r["same_process"] = a.pid == b.pid
        r["distinct_hwnd"] = a.hwnd != b.hwnd
        r["pids_during"] = sorted(office_pids(exe))
        r["visible_windows_of_a_pid"] = [
            {"hwnd": h, "class": class_name(h)} for h in top_level_windows(a.pid)
        ]
    except Exception as e:
        r["error"] = repr(e)
    finally:
        for sb in (b, a):
            if sb:
                close_sandbox(sb)
    time.sleep(2)
    r["pids_after_teardown"] = sorted(office_pids(exe))
    r["teardown_clean"] = set(r["pids_after_teardown"]) <= set(r["pre_existing_pids"])
    results[name] = r
    print(name, r)

save_json("s2_instances", results)
