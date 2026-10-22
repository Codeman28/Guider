# ADR-0002: Quyết định thiết kế Phase 2 (LLM layer)

- Trạng thái: **Đề xuất** — chưa sửa SPEC.md, chờ duyệt
- Ngày: 23/10/2026

## 1. Thẻ tác vụ trong Knowledge Pack được dùng trực tiếp (0 lần gọi Planner)

SPEC §6.4 mô tả Planner luôn là LLM call #1. Phase 2 thêm đường tắt: nếu câu hỏi khớp **rõ ràng** một thẻ đã
kiểm duyệt (`engine/knowledge/excel.cards.yaml`) thì dùng thẳng thẻ đó làm plan.

- "Rõ ràng" = khớp nguyên cụm từ khóa (100) hoặc mọi từ của một từ khóa nhiều từ (95), **và** không thẻ nào khác
  khớp ≥ 85, **và** câu hỏi không phải dạng khắc phục lỗi ("tại sao…", "bị lỗi…").
- Trên bộ eval 20 câu: 16 dùng thẻ trực tiếp (0 câu sai thẻ), 4 câu chồng chéo được chuyển cho LLM Planner.
- Lý do: S7 cho thấy model chạy được trên máy CPU phổ thông lập kế hoạch kém (liệt kê nhầm cả dãy tab, chọn sai
  intent) và chậm (10–400 s/lần). Thẻ đã kiểm duyệt cho kết quả tất định, đúng ADR-5 (giảm số lần gọi).
- Tắt được bằng `kem ask --no-cards` / `TutorialService(use_cards_directly=False)` để đo riêng LLM Planner.

## 2. Provider đồng bộ thay vì `async def`

SPEC §7.1 viết `async def complete_json`. Engine chạy mỗi phiên trên một worker thread (COM/UIA vốn đồng bộ), nên
provider là hàm đồng bộ. Không đổi hành vi; tránh trộn asyncio với COM apartment.

## 3. Ollama dùng API gốc `/api/chat` với `format` = JSON schema

Thay vì endpoint tương thích OpenAI. Lý do: S7 cho thấy `format` ép đầu ra theo grammar (100% JSON hợp lệ trên cả
4 model) và hỗ trợ `think: false` cho qwen3. Cloud (OpenRouter/Gemini) vẫn đi qua lớp tương thích OpenAI.

## 4. Kiểm tra COM có tham số nhưng trong danh sách đóng

`Expected.type = "com_check"` với `prop` phải là khóa của `verify/checks.py::COM_PROPS` (18 thuộc tính đọc được,
ví dụ `range.font.bold`, `window.freeze_panes`). Không có chuỗi nào được eval (SPEC §15).

## 5. Recipe lưu cả văn bản hướng dẫn

Ngoài plan + locator, recipe lưu văn bản Writer đã viết. Khi phát lại, nếu các bước ground ra cùng phần tử thì dùng
lại văn bản → 0 lần gọi LLM cho cả Planner lẫn Writer (tiêu chí "replay từ cache 0 call").

## 6. Blocklist mở rộng từ dump ribbon thật

`spikes/dump_ribbon.py` cho thấy các nút gọi mạng/cloud/add-in: Get Data, From Web, Refresh All, Stocks/Currencies,
Translate, Analyze Data, add-in của bên thứ ba, Add‑ins (tên dùng dấu gạch U+2011 — normalize đã xử lý), View Macros,
Screenshot, Comments/New Comment/Notes (comment mang tên tài khoản). Tất cả đã vào `safety/blocklist.yaml`.

## 7. Bộ lọc tiêu đề cửa sổ trong sanitizer

Tiêu đề cửa sổ Office có dạng `‪Book1‬  -  Excel` (hai dấu cách, có ký tự bidi) — regex ban đầu bỏ sót, unit test bắt
được và đã sửa.
