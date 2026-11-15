# ADR-0007 — Tự tìm cách làm việc mới: vòng "nhìn rồi làm"

Ngày: 15/11/2026 · Trạng thái: **đã làm**.

## Bối cảnh

Guider làm theo thẻ (kế hoạch viết sẵn) hoặc kế hoạch một lần do model viết. Việc nào không có thẻ, hay ảnh bài tập
có yêu cầu lạ, là không làm được; sửa xong thì cũng chỉ thêm đúng việc đó. Yêu cầu: hỏi gì cũng tự phân tích và làm
được, kể cả việc mới.

## Quyết định

1. **Vòng nhìn rồi làm** (`engine/kem_engine/agent/loop.py`, `Session._run_agent`): mỗi lượt Guider đưa cho Gemini
   - mục tiêu và các bước đã làm (kèm kết quả và "file thay đổi" gì),
   - trạng thái file đọc qua COM (Excel: giá trị/công thức bảng, khi chấm thêm định dạng từng ô, sheet, màu tab, bộ lọc,
     biểu đồ, định dạng có điều kiện; Word: từng đoạn `pN` với font/cỡ/màu/căn lề, đầu/chân trang, số trang, hướng giấy,
     lề, bảng, ảnh, mục lục; PowerPoint: slide đang chọn, khung chữ `sN.M`, chuyển trang, hiệu ứng, ảnh),
   - danh sách control đang hiện, đánh số `#id`, và ảnh chụp cửa sổ mẫu (vùng tài khoản đã làm mờ).
   Gemini chọn **một** hành động: click theo `#id`, gõ (ô Excel, đoạn Word, khung chữ PowerPoint), phím tắt, chọn vùng,
   nhập vào ô của hộp thoại, xong, hoặc bỏ cuộc. Guider làm bằng cùng actuator và SafetyGuard như bước của thẻ.
2. **An toàn**: không đưa Close/Minimize/Maximize, tab File, Save, Share vào danh sách; từ chối chuỗi phím Alt (hiện chữ
   gợi ý lên ảnh); phím tắt Excel phụ thuộc vùng chọn phải kèm ô; chọn vị trí không tồn tại chỉ tính là bước hỏng.
3. **Tự kiểm tra**: khi Gemini báo xong, một lượt chấm riêng so mục tiêu với trạng thái **ban đầu** và **cuối** (kèm ảnh):
   chưa đạt, làm thừa, hay dữ liệu cũ bị xê dịch đều là "chưa đạt" → báo lại lý do và làm tiếp (tối đa 2 lần). Bài ghi
   "đã làm xong" chỉ khi đạt; nếu không thì ghi làm được một phần và lý do.
4. **Đường làm sạch**: bước hỏng bị bỏ khỏi bài; chọn vùng lặp lại chỉ giữ lần cuối; bước bị Ctrl+Z hoàn tác bị bỏ cùng
   lệnh hoàn tác. Khi đã có bước bị hoàn tác, Guider chạy lại một lượt chỉ với các bước đúng, chấm lại, rồi mới xuất bài.
5. **Học bằng cách làm**: làm được việc mới (và lượt làm lại sạch đạt) thì lưu thành thẻ ở
   `%LOCALAPPDATA%\Kem\knowledge\<app>.self.yaml`; lần sau cùng câu hỏi là phát lại thẻ, không cần Gemini.
6. **Định tuyến**: thẻ khớp rõ thì dùng thẻ; thẻ chỉ khớp lỏng theo từ khóa thì hỏi nhanh Gemini (chữ, ~2 s) xem thẻ có đúng
   việc không; không có thẻ phù hợp mà có key Gemini thì dùng vòng nhìn rồi làm. Chế độ Giải bài tập: phần lời giải
   công thức không làm được thì vòng này làm tiếp trên bảng dựng lại.
7. Gemini bận (503/429) thì thử lại và xoay qua ba model; ngân sách thời gian của vòng ~110 s.

## Số đo (15/11/2026, máy người dùng, Gemini flash-lite)

| Việc chưa có thẻ | Kết quả | Bước | Thời gian |
|---|---|---|---|
| Kẻ viền tất cả ô của bảng | đạt | 3 | 80 s |
| Chèn một cột trống trước cột Doanh số | đạt, dữ liệu không lệch | 2 | 39 s |
| Đổi tên sheet và tô màu tab xanh lá | đạt | 9 | 152 s |
| Vẽ biểu đồ đường cho doanh số | đạt | 4 | 41 s |
| Word: số trang giữa chân trang | đạt | 4 | 91 s |
| Word: chữ "Bản nháp" ở đầu trang | đạt | 5 | 56 s |
| Word: tiêu đề màu đỏ cỡ 20 | đạt lượt đầu, lượt làm lại sạch chưa đạt → không lưu thẻ | 5 | 141 s |
| PowerPoint: slide "Kết luận" ở cuối | đạt | 3 | 40 s |

Mỗi lượt quyết định: đọc màn hình 1–3 s, Gemini 2–10 s.

## Hệ quả

- Cần key Gemini; không có key thì vẫn dùng thẻ và Planner như cũ.
- Việc nhiều bước có thể vượt 2 phút; việc ngắn 40–90 s.
- Độ tin cậy phụ thuộc thông tin trạng thái file: thứ gì chưa được đọc ra (vd một thuộc tính định dạng lạ) thì bước chấm
  có thể nhận định sai — bổ sung dần vào phần đọc trạng thái.
