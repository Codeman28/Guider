# Phase 3 — Nghiệm thu app Guider (23/10/2026)

Tiêu chí (SPEC §12, Phase 3): app desktop Tauri chạy được trọn luồng **đồng ý → kiểm tra máy → hỏi → xem làm mẫu
→ đọc tutorial**, hủy được bằng Esc, giao diện qua review của Impeccable, và **mỗi tutorial xong trong < 2 phút**.

Máy: i7-8565U, 16 GB RAM, chỉ CPU; M365 build 20326 (EN UI), 125% DPI; Ollama + `qwen3:1.7b`.

## Kết quả

| Hạng mục | Kết quả | Bằng chứng |
|---|---|---|
| Luồng end-to-end trong app thật (WebView2 qua CDP) | Đạt — PivotTable 71–92 s, tô màu 53 s, ảnh hiển thị đủ, 0 ảnh hỏng | `app/scripts/e2e-cdp.mjs`, `engine/.out/e2e/` |
| Màn hình đồng ý (3 câu + kiểm tra Excel và model) | Đạt | `.impeccable/review/consent.png` |
| Esc hủy khi đang làm mẫu | Đạt — dừng sạch, Excel hộp cát đóng, bài lưu "Đã dừng"; **Esc → app rảnh 4 s** (trước khi sửa 29 s) | `CANCEL=1 node scripts/e2e-cdp.mjs` |
| Review thiết kế (Impeccable finish) | **ship** sau khi sửa 7 phát hiện; DESIGN.md do documenter viết | `.impeccable/`, `DESIGN.md` |
| Giới hạn thời gian < 2 phút | **20/20 dưới 2 phút, tối đa 77 s** (lượt đầu); replay tối đa 15 s | `eval/reports/20261023-162317.md` |
| Kiểm thử đơn vị engine | 123 passed | `engine/tests` |

## Giới hạn 2 phút được đảm bảo thế nào

- `max_seconds_per_tutorial = 110` (trừ hao 10 s cho app), `planner_reserve_s = 60` giữ chỗ cho phần làm mẫu.
- Mỗi lệnh gọi LLM nhận timeout = thời gian còn lại − phần giữ chỗ; hết giờ thì Planner dùng thẻ khớp nhất,
  Writer dùng template — tutorial vẫn ra, không bao giờ treo chờ model.
- Model được nạp sẵn (warm-up) khi engine khởi động, nên câu hỏi đầu không phải chờ nạp model.
- Recipe cache: câu đã gặp phát lại với 0 lệnh gọi LLM.

## Sửa trong lần nghiệm thu này

- Hủy bằng Esc: kiểm tra hủy ngay sau khi Office khởi động xong, và không gọi Writer LLM cho bài đã hủy.

## Còn để người dùng quyết

