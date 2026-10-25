# ADR-0003 — Làm mẫu trên bản sao file của người dùng, Gemini free, Writer chạy nền

Ngày: 25/10/2026 · Trạng thái: **đã duyệt**

## Bối cảnh

Người dùng dùng thử bản cài (23/10) và nêu ba lỗi:

1. "Chỉ dùng ảnh có sẵn, không tự chụp được màn hình": Guider luôn làm mẫu trên file trống với dữ liệu giả, nên ảnh
   không giống file người dùng đang làm. Người dùng muốn ảnh chụp chính file của mình.
2. "Chạy quá lâu": phần làm mẫu thật chỉ ~30 s; phần còn lại là lời gọi LLM trên CPU (qwen3:1.7b, 15–40 s mỗi lần).
   Một câu hỏi ngoài thẻ (`Tô màu bảng`) tốn 3 lời gọi.
3. "Chưa dùng được model free": config có mục Gemini/OpenRouter nhưng tắt, chưa có model ID, app không có chỗ nhập key.

## Quyết định

### A. Chế độ "file của bạn" = làm trên bản sao (sửa SPEC §8)

- Người dùng chủ động chọn một file (.xlsx/.xlsm/.xls/.csv, .docx/.doc, .pptx/.ppt) trong app.
- Engine copy file vào `%LOCALAPPDATA%\Kem\work\<session>\` rồi mở **bản sao** trong sandbox (process riêng như cũ).
  File gốc không bao giờ được mở bằng Office hay ghi đè. Bản sao bị xóa trong teardown (đường dẫn nằm trong manifest).
- Macro bị tắt khi mở (`AutomationSecurity = msoAutomationSecurityForceDisable`), không cập nhật liên kết, không thêm
  vào danh sách file gần đây.
- Ảnh có dữ liệu thật: chỉ lưu local như mọi ảnh khác; không bao giờ gửi đi. Payload LLM vẫn chỉ có câu hỏi, tên nút
  và EnvProfile rút gọn (§7.3) — không có nội dung ô/văn bản.
- Tham chiếu vùng chọn trong thẻ (vd `A1:D21`, `p2`, `s2.1`) được ánh xạ sang file thật (vùng dữ liệu đang dùng,
  đoạn/slide có thật). Kiểm tra COM gắn với tham chiếu của file mẫu không áp dụng được thì được bỏ qua và ghi rõ
  trong trace ("không kiểm tra COM trên file của bạn") thay vì báo sai.
- PowerPoint vẫn từ chối khi PowerPoint đang mở (S2), kể cả ở chế độ này.

### B. Gemini free là provider cloud tùy chọn

- Người dùng tự tạo API key ở Google AI Studio và dán vào app; Guider không tạo tài khoản hay key thay người dùng.
- Key lưu mã hóa bằng Windows DPAPI (gắn với tài khoản Windows) tại `%LOCALAPPDATA%\Kem\secrets.bin`, không ghi
  vào settings.json, log hay trace.
- Khi bật, app hiện cảnh báo của ADR-4: gói free cho phép Google dùng dữ liệu gửi lên; Guider chỉ gửi payload đã lọc.
- Lỗi mạng/hết hạn mức → tự lùi về Ollama trên máy (fallback), không làm hỏng tutorial.

### C. Trả bài ngay, Writer LLM chạy nền

- Khi làm mẫu xong, tutorial được ghi ngay với lời văn template (đúng nhãn, đúng ảnh) và `tutorial.done` gửi ngay.
- Writer LLM chạy tiếp ở nền; xong thì ghi đè `tutorial.json` (chỉ phần lời văn) và gửi `tutorial.updated`.
  App tự tải lại bài đang mở. Hủy/đóng app thì bỏ phần viết lại, bài template vẫn hợp lệ.
- Ngân sách 2 phút tính tới lúc `tutorial.done`.

## Hệ quả

- SPEC v1.3: §8 thay gạch đầu dòng "Không đọc file người dùng" bằng quy tắc bản sao ở trên; §11 thêm `source_file`
  cho `tutorial.create`, notification `tutorial.updated`, `settings.set_api_key`.
- Không thay đổi blocklist, whitelist HWND, hay quy tắc không upload ảnh.
