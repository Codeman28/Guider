# ADR-0005 — Ảnh chụp vấn đề → file mẫu → hướng dẫn sửa

Ngày: 10/11/2026 · Trạng thái: **đã làm**.

## Bối cảnh

Người dùng muốn đưa file của mình **hoặc ảnh chụp vấn đề** lên Guider, rồi nhận hướng dẫn chi tiết cách sửa.
Quy trình: chụp ảnh → dựng file mẫu (hoặc dùng file người dùng đưa) → làm trên đó → chụp lại quy
trình → xuất hướng dẫn. Nhận file đã có từ ADR-0003; phần ảnh chưa có.

## Quyết định

1. **Ba cách đưa ảnh vào**: nút "Gửi ảnh vấn đề…" (hộp chọn file), dán ảnh vào ô chat (Ctrl+V), nút "Chụp cửa sổ
   Office" (PrintWindow cửa sổ Excel/Word/PowerPoint đang mở của người dùng; chỉ chụp, không bấm/gõ). Ảnh được
   copy và thu nhỏ (tối đa 1600 px) vào `%LOCALAPPDATA%\Kem\work\inbox\`; ảnh gốc không bị đổi.
2. **Đọc ảnh trên máy** (mặc định): model `gemma3:4b` qua Ollama (đã cài sẵn, không tải thêm). Trả về app, vấn
   đề, việc cần làm ("Cách …"), chữ/giá trị lỗi đọc được, và bảng nhìn thấy dạng `a | b | c` (ít token, vì trên
   CPU mỗi token tốn thời gian). OCR của Windows chỉ dùng làm đường lui khi không có model: nó bỏ dấu tiếng Việt
   và bỏ sót `#N/A`, đưa vào prompt còn làm model chép lỗi theo.
3. **Chọn bài**: khớp từ khóa + so tên bài; nếu khớp rõ *và* tên bài giống việc cần làm (≥ 70) thì dùng luôn,
   không thì model chọn trong tối đa 10 bài đã học (chỉ chữ, không ảnh); không bài nào hợp thì câu "Cách …" đi tới
   Planner như câu hỏi thường.
4. **File làm mẫu**:
   - người dùng có đưa file → bản sao file đó (ADR-0003);
   - bài có bước gõ công thức → bảng mẫu của chính bài đó (địa chỉ ô trong công thức chỉ đúng trên bảng ấy), hướng
     dẫn ghi rõ "áp dụng cùng cách vào file của bạn";
   - còn lại → **dựng lại bảng/đoạn chữ trong ảnh** thành file mẫu trong sandbox. Ô lỗi được tái hiện bằng công
     thức gây đúng lỗi đó (`#N/A` → `=NA()`, `#DIV/0!` → `=1/0`…), công thức lạ giữ dạng chữ. Tham chiếu ô của
     thẻ được ánh xạ như với file người dùng; kiểm tra COM theo ô của thẻ được bỏ qua và ghi trong trace.
5. **Hướng dẫn** có thêm mục "Vấn đề của bạn": ảnh người dùng gửi, tóm tắt vấn đề, chữ đọc được, và đã làm mẫu trên
   file nào. Có trong bản xuất Markdown/HTML. Writer chạy nền giữ nguyên mục này.
6. **Gemini đọc ảnh, bật mặc định**: setting `vision_cloud`, mặc định bật khi đã lưu
   key Gemini, tắt được trong Cài đặt. Ô chat báo trước mỗi ảnh rằng ảnh sẽ được gửi lên Gemini; Cài đặt cảnh báo
   gói miễn phí cho phép Google dùng dữ liệu. Không có key, đã tắt, hoặc lỗi mạng → đọc trên máy.

## Số đo (10/11/2026, i7-8565U, không GPU)

| Bước | Thời gian |
|---|---|
| gemma3:4b đọc một ảnh mới (riêng phần ảnh) | ~73 s |
| Cả lượt đọc (ảnh + trả lời) | 100–123 s |
| Model chọn bài (chữ) | ~12 s |
| Làm mẫu cố định dòng tiêu đề trên bảng dựng lại | 15 s |
| Tổng, ảnh Excel thật → hướng dẫn | 142 s |
| Gemini đọc cùng ảnh (chép bảng đúng dấu) | 3,7 s |

Đọc ảnh trên máy không vừa giới hạn 2 phút, nên phần làm mẫu giữ ngân sách 2 phút riêng, tính từ sau khi đọc
xong; với Gemini cả lượt tính chung một ngân sách. Muốn nhanh hơn mà vẫn giữ ảnh trên máy thì cần model đọc ảnh nhỏ
hơn (phải tải thêm, chờ người dùng đồng ý) hoặc máy có GPU.

## Hệ quả

- SPEC v1.5: §7.3 ngoại lệ ảnh vấn đề, §8 quy tắc ảnh, §11 thêm `problem_image` và các lệnh `problem.*`.
- Mã: `engine/kem_engine/vision/` (problem.py, ocr.ps1), `TutorialService.create_from_problem`, `SandboxHandle.sample`,
  `Tutorial.problem`; app: ChatColumn (ảnh, dán, chụp), StepStack (pha đọc ảnh), TutorialView (mục Vấn đề), Cài đặt.
