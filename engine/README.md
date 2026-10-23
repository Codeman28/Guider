# Guider engine (Python sidecar)

Phase 1: CLI làm mẫu tác vụ Excel bằng plan viết tay, không dùng LLM (SPEC §12).

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -e .[dev]
.venv/Scripts/kem tasks
.venv/Scripts/kem run --task pivot_basic              # 1 tutorial → %LOCALAPPDATA%\Kem\tutorials\<id>_pivot_basic\
.venv/Scripts/kem run --task pivot_basic --repeat 10  # nghiệm thu
.venv/Scripts/kem run --task pivot_basic --width 1024 # cửa sổ hẹp: ribbon thu gọn → engine tự chèn bước mở nhóm
.venv/Scripts/python -m pytest                        # unit test với dữ liệu giả, không cần Office
```

Mỗi tutorial: `tutorial.json` (nội dung hiển thị), `trace.json` (bước đã ground + locator + kết quả verify),
`manifest.json` (file do phiên tạo + báo cáo teardown), `step_NN.png` (ảnh đã che avatar và vẽ chú thích).

Luồng: `orchestrator/session.py` — SETUP (COM tạo workbook trống, nạp fixture) → mỗi bước:
GROUND (`uia/snapshot.py` FindAll có cache + `grounding/grounder.py` fuzzy/alias/luật mở nhóm thu gọn)
→ CAPTURE (`capture/` PrintWindow + ghép popup, `annotate/` che danh tính rồi vẽ khung/mũi tên)
→ `safety/guard.py` → ACT (`uia/actuator.py`, chỉ UIA pattern) → VERIFY (`verify/`, UIA hoặc COM)
→ TEARDOWN luôn chạy (đóng dialog của sandbox, Esc, Close không lưu, Quit, nhả COM ref) → WRITE (`writer/template.py`).

Lưu ý runtime (`env/runtime.py`): phải đặt DPI awareness và import stack UIA (pywinauto đặt COM MTA)
**trước** khi pywin32 khởi tạo COM; ngược thứ tự thì proxy Excel chết sau lần quét UIA đầu tiên.
