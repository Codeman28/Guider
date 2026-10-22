"""S7: Which local Ollama model returns schema-valid Planner JSON most reliably?

Usage: python s7_ollama_planner.py <model> [<model> ...]
Base URL comes from env KEM_OLLAMA_BASE_URL (default http://127.0.0.1:11434/v1, SPEC §7.2).
Uses Ollama's OpenAI-compatible endpoint with response_format json_schema
(TODO(verify): https://docs.ollama.com/capabilities/structured-outputs).
"""
import json
import os
import sys
import time
from typing import Literal, Optional

from pydantic import BaseModel, ValidationError

from _common import save_json

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

PROMPTS = [
    "Cách tạo PivotTable trong Excel",
    "làm sao chèn biểu đồ cột trong excel",
    "định dạng có điều kiện tô đỏ ô lớn hơn 100",
    "cố định dòng đầu tiên khi cuộn trang tính",
    "lọc dữ liệu theo cột Tháng",
    "sắp xếp doanh số từ lớn đến bé",
    "gộp ô A1 đến D1 và căn giữa",
    "chèn bảng (Format as Table) cho vùng dữ liệu",
    "tải Excel miễn phí ở đâu",
    "gửi file excel qua email cho sếp",
]

RIBBON_TABS = ["Home", "Insert", "Draw", "Page Layout", "Formulas", "Data", "Review", "View", "Help"]


def run(model: str) -> dict:
    from openai import OpenAI

    client = OpenAI(base_url=os.environ.get("KEM_OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
                    api_key="ollama")
    schema = Plan.model_json_schema()
    rows = []
    for q in PROMPTS:
        user = json.dumps({"question": q, "app": "excel", "ui_lang": "en-US",
                           "ribbon_tabs": RIBBON_TABS}, ensure_ascii=False)
        t0 = time.perf_counter()
        row = {"q": q}
        try:
            resp = client.chat.completions.create(
                model=model, temperature=0.2, max_tokens=2000,
                messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                response_format={"type": "json_schema",
                                 "json_schema": {"name": "plan", "schema": schema}},
            )
            text = resp.choices[0].message.content
            plan = Plan.model_validate_json(text)
            row.update(valid=True, in_scope=plan.in_scope, n_steps=len(plan.steps))
        except ValidationError as e:
            row.update(valid=False, error=str(e)[:200])
        except Exception as e:
            row.update(valid=False, error=repr(e)[:200])
        row["latency_s"] = round(time.perf_counter() - t0, 2)
        rows.append(row)
        print(model, row)
    ok = [r for r in rows if r["valid"]]
    return {"model": model, "valid_rate": len(ok) / len(rows),
            "avg_latency_s": round(sum(r["latency_s"] for r in rows) / len(rows), 2), "rows": rows}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    save_json("s7_ollama_planner", [run(m) for m in sys.argv[1:]])
