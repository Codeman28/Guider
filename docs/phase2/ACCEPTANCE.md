# Phase 2 — Nghiệm thu (23/10/2026)

Tiêu chí (SPEC §12): bộ eval 20 tác vụ Excel — **≥ 80% hoàn thành đủ bước; trung bình ≤ 2,5 LLM call/tutorial;
replay từ cache 0 call.**

Máy: i7-8565U, 16 GB RAM, **chỉ CPU**; M365 build 20326 (EN UI), 125% DPI; Ollama 0.40.8 + `qwen3:1.7b`.
Một tác vụ "đạt" = `status ok` (mọi bước xác minh được) **và** kết quả COM của tác vụ đúng như mong đợi
(`success_check` của thẻ tương ứng, kiểm tra sau bước cuối).

## Kết quả (máy để yên)

| Lượt | Hoàn thành | LLM call TB | Tối đa | Thời gian TB | Báo cáo |
|---|---|---|---|---|---|
| 1 — lần đầu | **18/20 (90%)** | **1,10** | 2 | 44 s | `eval/reports/20261023-102030.md` |
| 2 — replay từ recipe | **20/20 (100%)** | 0,10 | 1 | 14 s | (cùng file) |
| Chạy lại e12, e17 sau khi sửa lỗi | 2/2 + replay 2/2 | 1,00 / **0** | 1 / 0 | 35 s / 9 s | `eval/reports/` mới nhất |

- Mọi tác vụ có recipe đều phát lại với **0 lần gọi LLM** (18/18 trong lượt 2; e12/e17 ở lượt 2 dùng thẻ vì lượt 1 crash nên chưa có recipe).
- Nguồn kế hoạch lượt 1: 16 thẻ trực tiếp (0 call Planner), 4 câu mơ hồ → LLM **chọn thẻ** (1 call) — cả 4 chọn đúng.
- Writer LLM được giữ ở 14/18 tutorial; 4 tutorial lùi về template vì model không in đậm đúng nhãn.

**Đạt cả ba tiêu chí.**

## Hai lỗi ở lượt 1 và cách sửa

e12, e17 crash khi ghi dữ liệu mẫu ngay sau `Workbooks.Add()`: Excel trả `DISP_E_EXCEPTION` với mã riêng
`0x800AC472` (chưa sẵn sàng). `com_retry` giờ coi mã này là "bận" và thử lại; ghi fixture đi qua `com_retry`.
Chạy lại: 2/2 đạt, replay 0 call.

## Những gì đã học qua 4 lần chạy eval

| Lần | Điều kiện | Lượt 1 | Phát hiện → sửa |
|---|---|---|---|
| 1 (02:03) | máy để yên, bản đầu | 5/7 (dừng giữa chừng) | Planner LLM trả `control_type` chữ thường → schema chỉ cho tên UIA, Grounder chuẩn hóa |
| 2 (09:39) | người dùng đang dùng máy | 15/20 | LLM tự lập kế hoạch sai (sai thẻ ribbon, bước thừa) → LLM chỉ **chọn thẻ**; bấm toggle 2 lần làm mất kết quả → kiểm tra lại trước khi thử lại |
| 3 (10:13) | người dùng đang dùng máy | dừng | Menu/gallery đóng khi cửa sổ khác lấy focus → tự mở lại menu; chọn lại vùng dữ liệu trước mỗi bước |
| 4 (10:20) | **máy để yên** | **18/20** | `0x800AC472` khi ghi fixture → thử lại |

Kết luận vận hành: **làm mẫu cần người dùng không thao tác** trong lúc chạy (đúng ADR-0001 mục 1). Engine đã chịu được
một phần nhiễu (mở lại menu, khôi phục vùng chọn, không lặp toggle), nhưng số đo nghiệm thu lấy ở điều kiện máy để yên.

## Unit test

113 test, không cần Office. `safety/` và `llm/sanitizer.py`: **100% branch coverage** (SPEC §15).

## Chưa làm / giới hạn

- Thẻ có mục `unverified` (chart_pie "Pie", freeze_top_row "Freeze Top Row", orientation "Landscape") đã ground được
  trên máy này trừ orientation_landscape (không có trong bộ 20 câu) — cần cập nhật cờ trong thẻ sau khi eval thêm.
- Planner LLM tự do (khi không thẻ nào khớp) vẫn yếu với model 1.7B — chưa có tác vụ ngoài thẻ trong bộ eval.
- Chưa đo trên máy giao diện tiếng Việt, DPI khác 125%, cửa sổ hẹp (ma trận §13).
- ADR-0002 chờ duyệt trước khi cập nhật SPEC.md.
