"""Phase 2 eval runner (SPEC §12–13).

  python eval/runner.py                 # pass 1 (fresh recipe DB) + pass 2 (replay from cache)
  python eval/runner.py --only e01 e04  # subset
  python eval/runner.py --no-cards      # force the LLM Planner (measures the model, slow on CPU)

Writes eval/reports/<timestamp>.json and .md. Uses a throwaway recipe DB so results are reproducible.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--no-cards", action="store_true")
    ap.add_argument("--no-replay", action="store_true")
    args = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")

    from kem_engine.env import runtime
    runtime.init()
    import structlog
    import yaml
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(30))
    from kem_engine.orchestrator.service import TutorialService
    from kem_engine.recipes.store import Store

    tasks = yaml.safe_load((ROOT / "eval" / "tasks.yaml").read_text(encoding="utf-8"))["tasks"]
    from kem_engine.intent.knowledge import KnowledgePack
    cards = KnowledgePack().by_id
    if args.only:
        tasks = [t for t in tasks if t["id"] in args.only]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    work = ROOT / "engine" / ".out" / f"eval-{stamp}"
    work.mkdir(parents=True)
    svc = TutorialService(work / "tutorials", store=Store(work / "eval.db"), use_cards_directly=not args.no_cards)

    rows = []
    passes = [1] if args.no_replay else [1, 2]
    for p in passes:
        for t in tasks:
            t0 = time.monotonic()
            try:
                r = svc.create(t["query"], success_check=cards[t["expect_task"]].to_plan().success_check)
                d = r.to_dict()
            except Exception as e:  # keep going; record the crash
                d = {"kind": "error", "answer": repr(e)}
            trace_task = None
            if d.get("path"):
                tr = json.loads((Path(d["path"]) / "trace.json").read_text(encoding="utf-8"))
                trace_task = tr["task_canonical"]
                steps = tr["steps"]
                d["steps"] = len(steps)
                d["steps_verified"] = sum(s["verified"] for s in steps)
                d["ambiguous"] = sum(s["ambiguous"] for s in steps)
            row = {"pass": p, "id": t["id"], "query": t["query"], "expect_task": t["expect_task"],
                   # ok = demonstrated end to end AND the expected outcome holds (COM success_check)
                   "task": trace_task, "ok": d.get("status") == "ok",
                   "seconds": round(time.monotonic() - t0, 1), **{k: d.get(k) for k in (
                       "kind", "status", "llm_calls", "plan_source", "writer_source", "steps", "steps_verified",
                       "ambiguous", "answer", "path")}}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)

    out = ROOT / "eval" / "reports"
    out.mkdir(exist_ok=True)
    (out / f"{stamp}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# Eval {stamp}", "", f"cards_directly={not args.no_cards}", ""]
    for p in passes:
        rs = [r for r in rows if r["pass"] == p]
        n = len(rs)
        ok = sum(r["ok"] for r in rs)
        calls = [r["llm_calls"] or 0 for r in rs]
        lines += [f"## Lượt {p}" + (" (replay từ recipe cache)" if p == 2 else ""), "",
                  f"- Hoàn thành: **{ok}/{n}** ({ok / n:.0%})" if n else "- (rỗng)",
                  f"- LLM call trung bình: **{sum(calls) / max(n, 1):.2f}**, tối đa {max(calls, default=0)}",
                  f"- Thời gian trung bình: {sum(r['seconds'] for r in rs) / max(n, 1):.0f} s, tối đa "
                  f"{max((r['seconds'] for r in rs), default=0):.0f} s",
                  f"- Vượt 2 phút: **{sum(r['seconds'] >= 120 for r in rs)}/{n}**", "",
                  "| id | ok | task | status | calls | plan | writer | bước verify | giây |", "|---|---|---|---|---|---|---|---|---|"]
        for r in rs:
            lines.append(f"| {r['id']} | {'✓' if r['ok'] else '✗'} | {r['task']} | {r['status'] or r['kind']} | "
                         f"{r['llm_calls']} | {r['plan_source']} | {r['writer_source']} | "
                         f"{r['steps_verified']}/{r['steps']} | {r['seconds']} |")
        lines.append("")
    (out / f"{stamp}.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    first = [r for r in rows if r["pass"] == 1]
    return 0 if first and sum(r["ok"] for r in first) / len(first) >= 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())
