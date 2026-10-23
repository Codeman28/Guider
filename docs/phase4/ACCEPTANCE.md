# Phase 4 — Nghiệm thu Word và PowerPoint (23/10/2026)

Tiêu chí (SPEC §12, Phase 4): mỗi app 10 tác vụ, **≥ 75% hoàn thành**; vẫn giữ **mỗi tutorial < 2 phút**;
PowerPoint không bao giờ dùng chung tiến trình với file của người dùng.

Máy: i7-8565U, 16 GB RAM, chỉ CPU; M365 build 20326 (EN UI), 125% DPI; `qwen3:1.7b`. Máy để yên khi chạy.
"Đạt" = `status ok` (mọi bước xác minh được) **và** kiểm tra COM của thẻ đúng sau bước cuối.

## Kết quả

| App | Lượt | Hoàn thành | LLM call TB | Thời gian TB / tối đa | Báo cáo |
|---|---|---|---|---|---|
| Word | 1 | **10/10** | 1,10 | 42 s / **64 s** | `eval/reports/20261023-171341.md` |
| Word | 2 — replay | **10/10** | 0,10 | 22 s / 30 s | (cùng file) |
| PowerPoint | 1 | **10/10** | 1,20 | 29 s / **34 s** | `eval/reports/20261023-173143.md` |
| PowerPoint | 2 — replay | **10/10** | **0** | 10 s / 16 s | (cùng file) |
| Word (5 thẻ sửa `within`, chạy lại) | 1 | 5/5 | 1,00 | 37 s / 44 s | `eval/reports/20261023-173814.md` |

**Không tutorial nào vượt 2 phút** (tối đa 64 s). Các câu mơ hồ (p07/p08: "chuyển trang mờ dần" và "kiểu đẩy")
đi qua LLM chọn thẻ và chọn đúng.

Thử an toàn: khi một PowerPoint khác đang chạy, `office.setup` từ chối với thông báo
"Hãy đóng PowerPoint rồi hỏi lại…" (S2: PowerPoint chỉ có một tiến trình). Đã kiểm tra thật.

## Những gì phải sửa để đạt (bài học)

1. Nút Bold/Italic/Center… của Word và PowerPoint **chỉ có Toggle** (không có Invoke) → actuator dùng toggle khi
   `invoke` gặp nút như vậy.
2. Ở cửa sổ 1280 px, nhóm **Paragraph** (Word) và **Slides** (PowerPoint) bị thu gọn — add-in WPS PDF, AI Tools
   chiếm chỗ ribbon. Thẻ nay ghi `within` nhóm cho mọi nút tab Home, cơ chế sửa (S1) tự mở nhóm.
3. Màu "Red" của M365 lưu là 238 → kiểm tra "màu khác tự động" (`gte 1`) thay vì so 255.
4. Mục lục cần đề mục: fixture Word gán Heading 1 (theo id dựng sẵn, chạy được với mọi ngôn ngữ giao diện).

## Giới hạn đã biết

- **Chèn bảng trong Word chưa làm mẫu được**: ô lưới "NxM Table" báo *disabled* qua UIA (Guider không bấm phần tử
  disabled), và Invoke "Insert Table..." không mở hộp thoại. Thẻ này được bỏ khỏi bộ thẻ; câu hỏi về bảng Word sẽ
  đi đường LLM Planner và có thể trả về hướng dẫn chưa làm mẫu được.
- Tên tiếng Việt trong thẻ là bí danh chưa kiểm chứng (chưa có Office giao diện tiếng Việt).
