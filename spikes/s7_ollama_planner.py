"""S7: Which local Ollama model returns schema-valid Planner JSON most reliably?

Usage: python s7_ollama_planner.py <model> [<model> ...]
Base URL from env KEM_OLLAMA_URL (default http://127.0.0.1:11434). Uses the native /api/chat with
`format` = JSON schema (structured outputs) and `think: false` for thinking-capable models.
TODO(verify): https://docs.ollama.com/capabilities/structured-outputs ,
https://docs.ollama.com/capabilities/thinking
"""
import json
import os
import sys
import time
from typing import Literal, Optional

from pydantic import BaseModel, ValidationError

from _common import save_json  # noqa: F401

Intent = Literal["select_ribbon_tab", "invoke", "expand", "select_item", "toggle", "set_value",
                 "type_text", "key_combo", "select_range", "wait_for"]


class Within(BaseModel):
    names: list[str]
    control_type: str


class Target(BaseModel):
    names: list[str]
    control_type: str
    within: Optional[Within] = None


class Expected(BaseModel):
    type: str
    names: Optional[list[str]] = None


class Step(BaseModel):
    id: int
    intent: Intent
    target: Optional[Target] = None
    expected: Optional[Expected] = None
    value: Optional[str] = None


class Plan(BaseModel):
    in_scope: bool
    reason: Optional[str] = None
    title: str
    fixture_id: Optional[str] = None
    steps: list[Step]


SYSTEM = ("Bạn lập kế hoạch thao tác giao diện Microsoft 365 trên Windows. Chỉ dùng các intent trong "
          "danh sách. Không sinh tọa độ. Với mỗi target, liệt kê tên nút khả dĩ bằng cả tiếng Anh và "
          "tiếng Việt. Nếu tác vụ không thể làm mẫu trong một file trống, trả in_scope=false kèm lý do. "
          "Chỉ trả JSON đúng schema.")

PROMPTS = [  # (question, expected in_scope)
    ("Cách tạo PivotTable trong Excel", True),
    ("làm sao chèn biểu đồ cột trong excel", True),
    ("định dạng có điều kiện tô đỏ ô lớn hơn 100", True),
    ("cố định dòng đầu tiên khi cuộn trang tính", True),
    ("lọc dữ liệu theo cột Tháng", True),
    ("sắp xếp doanh số từ lớn đến bé", True),
    ("gộp ô A1 đến D1 và căn giữa", True),
    ("chèn bảng (Format as Table) cho vùng dữ liệu", True),
    ("tải Excel miễn phí ở đâu", False),
    ("gửi file excel qua email cho sếp", False),
]

RIBBON_TABS = ["Home", "Insert", "Draw", "Page Layout", "Formulas", "Data", "Review", "View", "Help"]


def chat(model: str, system: str, user: str, schema: dict, timeout: float = 600) -> str:
    import urllib.error
    import urllib.request
    body = {"model": model, "stream": False, "think": False, "format": schema,
            "options": {"temperature": 0.2, "num_predict": 2000},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    url = os.environ.get("KEM_OLLAMA_URL", "http://127.0.0.1:11434") + "/api/chat"
    for attempt in range(2):
        req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())["message"]["content"]
        except urllib.error.HTTPError as e:
            # models without thinking support may reject the `think` field
            if attempt == 0 and "think" in e.read().decode(errors="ignore").lower():
                body.pop("think")
                continue
            raise


def run(model: str) -> dict:
    schema = Plan.model_json_schema()
    chat(model, "Trả lời OK.", "ping", {"type": "object"})  # warm-up: load weights, not timed
    rows = []
    for q, want_in_scope in PROMPTS:
        user = json.dumps({"question": q, "app": "excel", "ui_lang": "en-US",
                           "ribbon_tabs": RIBBON_TABS}, ensure_ascii=False)
        t0 = time.perf_counter()
        row = {"q": q}
        try:
            plan = Plan.model_validate_json(chat(model, SYSTEM, user, schema))
            row.update(valid=True, in_scope=plan.in_scope, scope_ok=plan.in_scope == want_in_scope,
                       n_steps=len(plan.steps), first=[(s.intent, s.target.names if s.target else None)
                                                       for s in plan.steps[:3]])
        except ValidationError as e:
            row.update(valid=False, scope_ok=False, error=str(e)[:200])
        except Exception as e:
            row.update(valid=False, scope_ok=False, error=repr(e)[:200])
        row["latency_s"] = round(time.perf_counter() - t0, 1)
        rows.append(row)
        print(model, json.dumps(row, ensure_ascii=False), flush=True)
    n = len(rows)
    return {"model": model, "valid_rate": sum(r["valid"] for r in rows) / n,
            "scope_acc": sum(r["scope_ok"] for r in rows) / n,
            "avg_latency_s": round(sum(r["latency_s"] for r in rows) / n, 1),
            "max_latency_s": max(r["latency_s"] for r in rows), "rows": rows}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    # Resumable: results are merged per model into the JSON file after each model finishes.
    from _common import OUT
    path = OUT / "s7_ollama_planner.json"
    done = {r["model"]: r for r in json.loads(path.read_text(encoding="utf-8"))} if path.exists() else {}
    for m in sys.argv[1:]:
        done[m] = run(m)
        save_json("s7_ollama_planner", list(done.values()))
