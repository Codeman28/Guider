"""`kem run --task pivot_basic [--repeat N]` — Phase 1 CLI (SPEC §12)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PLANS = Path(__file__).resolve().parents[1] / "plans"


def default_out() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "Kem" / "tutorials"


def list_tasks() -> list[str]:
    return sorted(p.stem for p in PLANS.glob("*.json"))


def _progress(m: dict) -> None:
    print(f"[{m['state']:<9}] {m['message']}", flush=True)


def leftover_check(pid: int) -> dict:
    from .env import win32
    return {"sandbox_process_alive": win32.process_alive(pid)}


def cmd_run(args) -> int:
    from .env import runtime
    runtime.init()  # DPI awareness + COM apartment, before anything else (S5)

    import structlog
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(30))

    from .models import Plan
    from .orchestrator.session import Session

    plan = Plan.model_validate_json((PLANS / f"{args.task}.json").read_text(encoding="utf-8"))
    out_root = Path(args.out) if args.out else default_out()
    summary = []
    for i in range(1, args.repeat + 1):
        if args.repeat > 1:
            print(f"=== Lần {i}/{args.repeat} ===", flush=True)
        s = Session(plan, out_root, progress=_progress, window_logical=(args.width, 800))
        try:
            r = s.run()
        except Exception as e:
            summary.append({"run": i, "status": "error", "error": repr(e)})
            print(f"LỖI: {e!r}", flush=True)
            continue
        alive = s.sb is not None and leftover_check(s.sb.pid)["sandbox_process_alive"]
        row = {"run": i, "status": r.tutorial.status, "seconds": round(r.seconds, 1),
               "steps": len(r.tutorial.steps), "out": str(r.out_dir),
               "teardown_clean": bool(r.teardown.get("process_exited")) and not alive,
               "forced": r.teardown.get("forced", False)}
        summary.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if r.tutorial.status == "cancelled":
            break
        time.sleep(1)
    ok = all(r.get("status") == "ok" and r.get("teardown_clean") for r in summary)
    print(f"Tổng: {sum(r.get('status') == 'ok' for r in summary)}/{len(summary)} ok, "
          f"teardown sạch {sum(bool(r.get('teardown_clean')) for r in summary)}/{len(summary)}")
    return 0 if ok and len(summary) == args.repeat else 1


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Vietnamese output on cp1252 consoles
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="kem")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="làm mẫu một tác vụ bằng plan viết tay")
    run.add_argument("--task", required=True, choices=list_tasks())
    run.add_argument("--repeat", type=int, default=1)
    run.add_argument("--width", type=int, default=1280, help="độ rộng logic cửa sổ sandbox (hẹp → ribbon thu gọn)")
    run.add_argument("--out", help="thư mục gốc chứa tutorial (mặc định %%LOCALAPPDATA%%\\Kem\\tutorials)")
    sub.add_parser("tasks", help="liệt kê tác vụ có plan")
    args = ap.parse_args(argv)
    if args.cmd == "tasks":
        print("\n".join(list_tasks()))
        return 0
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
