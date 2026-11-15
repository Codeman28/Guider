# ADR-0008 — Làm lại đến khi được, ghi nhớ bài học, tự luyện tiếp

Ngày: 15/11/2026 · Trạng thái: **đã làm**.

## Bối cảnh

Vòng "nhìn rồi làm" (ADR-0007) chỉ chạy một lượt: hết thời gian hay hỏng ba bước liền là dừng, bài ghi "làm được một
phần". Thẻ có sẵn mà hỏng trên máy người dùng cũng dừng luôn. Những gì một lượt thất bại học được thì mất. Yêu cầu:
không biết thì phải tìm cách đến khi làm được; sai thì làm lại; chưa được thì nhận là chưa được nhưng phải học tiếp.

## Quyết định

1. **Làm lại từ đầu, nhiều lượt** (`TutorialService._create`, bước 3c). Lượt chưa đạt thì Guider mở lại file mẫu sạch
   và làm lại, tối đa `MAX_AGENT_ROUNDS = 3` lượt cho một câu hỏi; lượt sau có thêm 40 s. Mỗi lượt mới đọc các bài học
   vừa rút ra từ lượt trước.
2. **Thẻ hỏng thì tự tìm cách khác**: thẻ hay công thức đã lưu mà làm không được trên máy này thì vòng nhìn rồi làm nhận
   việc, kèm ghi chú bước nào của thẻ đã hỏng. Làm được thì thẻ tự học cũ (`agent_…`) bị thay bằng đường mới.
3. **Bài học** (`agent/memory.py`): sau mỗi lượt chưa đạt, và sau lượt đạt mà có bước hỏng, một câu hỏi chữ ngắn cho
   Gemini rút ra 1–3 bài học dùng lại được (tên nút, menu, hộp thoại, phím tắt; không nhắc số liệu của file mẫu). Không
   gọi được Gemini thì ghi chính các bước đã hỏng. Bài học lưu ở `%LOCALAPPDATA%\Kem\knowledge\<app>.lessons.json`
   (tối đa 300 mỗi app). Mọi lượt sau đọc tối đa 8 bài: bài của việc giống nhất trước, rồi bài gần đây nhất.
4. **Hàng đợi luyện tập**: hết lượt mà vẫn chưa đạt thì bài ghi rõ là chưa làm được, và việc đó vào
   `%LOCALAPPDATA%\Kem\knowledge\practice.json`. Guider luyện lại từng việc, việc ít lần thử nhất trước, tối đa 6 lần
   mỗi việc:
   - tự động khi máy rảnh 10 phút (cài đặt `auto_practice`, mặc định bật); người dùng chạm chuột hay bàn phím là dừng
     ngay (InputGuard);
   - hoặc bấm "Luyện ngay một việc" trong Cài đặt → Guider tự học.
   Luyện được thì lưu thẻ, bài hướng dẫn ở lại thư viện và app báo "Guider vừa tự học được: …". Luyện chưa được thì chỉ
   giữ bài học, bài hướng dẫn của lượt đó bị xóa.
5. **RPC**: `practice.list` → `{goals, pending, auto}`; `practice.run` → `{started, session_id}`, rồi thông báo
   `practice.progress` và `practice.done {app, goal, solved, status, tutorial_id}`; `settings.set` nhận `auto_practice`.

Sửa kèm, tìm ra khi chạy lại việc "tiêu đề đỏ cỡ 20":
- Nhóm ribbon bị thu gọn thành một nút (cửa sổ hẹp): bước mở nhóm trước đây bị xóa vì kiểm tra "mở menu" không thấy
  popup, nên lượt phát lại không tìm ra nút bên trong. Giờ bước bấm nhóm được giữ, các control hiện ra sau đó được gắn
  `within` = tên nhóm; thẻ học được bỏ bước mở nhóm và để grounder tự mở khi ribbon hẹp (S1).
- Bước báo "không thấy kết quả mong đợi" nhưng thực ra đã làm đổi gì đó (mở popup, đổi file) được giữ trong đường làm.
- Ô ComboBox được bấm vào phần chữ, không vào mũi tên; nếu con trỏ vẫn nằm trong tài liệu thì không gõ (trước đây "20"
  rơi vào văn bản, thay mất tiêu đề).
- Nút không có kiểu mở UIA (bảng màu trong hộp thoại Font) thì bấm chuột thật.

## Số đo (15/11/2026, máy người dùng, Gemini flash-lite)

| Việc | Trước | Sau |
|---|---|---|
| Word: tiêu đề màu đỏ, cỡ 20 | lượt đầu đạt, phát lại hỏng, không học | đạt 70–103 s, học thẻ; hỏi lại câu đó: phát lại thẻ 33 s, không gọi Gemini |
| Word: chèn mục lục tự động ở đầu văn bản (mới) | — | đạt 70 s, học thẻ |
| Excel: PivotTable tổng Doanh số theo Khu vực (mới) | 3 lượt, 22 phút, chưa đạt (mỗi lần đọc file khi hộp thoại mở bị treo ~4 phút) → vào hàng đợi | đạt 43 s ở lượt đầu, hàng đợi ghi "đã tự học được" |

Lượt PivotTable thất bại cũng cho thấy bài học có thể bị nhiễu bởi lỗi của chính Guider ("ứng dụng bận", khuyên dùng
Alt+N+V); câu hỏi rút bài học nay dặn bỏ qua lỗi kỹ thuật và không khuyên chuỗi phím Alt. Các bài học nhiễu đó đã bị xóa.

Sửa kèm: khi Excel đang mở hộp thoại, Guider không đọc file qua COM (Excel không trả lời cho đến khi hộp thoại đóng)
mà dùng lại lần đọc gần nhất, kèm ghi chú.

## Giới hạn

- Cần key Gemini. Ba lượt có thể mất 5–7 phút cho một câu hỏi khó.
- "Đến khi làm được" có giới hạn: 3 lượt mỗi câu hỏi, rồi 6 lần luyện mỗi việc. Việc vẫn không được thì nằm lại trong
  danh sách để người dùng thấy, Guider không tự thử nữa.
- Bài học do model rút ra, có thể sai. Chúng chỉ là gợi ý cho lượt sau; kết quả vẫn do lượt chấm quyết định.
