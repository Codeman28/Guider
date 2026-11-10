# ADR-0006 — Hai chế độ: Hướng dẫn và Giải bài tập

Ngày: 10/11/2026 · Trạng thái: **đã làm**.

## Bối cảnh

Với ảnh một bảng nhân viên và câu hỏi tính tổng doanh số, Guider (ADR-0005) chọn được bài SUM nhưng làm
mẫu trên **bảng mẫu có sẵn** (`=SUM(D2:D21)`), vì công thức của bài chỉ đúng trên bảng mẫu. Người dùng thấy
bảng trong ảnh không được dựng lại. Vì vậy tách hai chế độ:

- **Hướng dẫn** (mục chính): chỉ hỏi cách làm một thao tác; Guider làm mẫu trên file mẫu của bài (hoặc bản sao
  file người dùng chọn).
- **Giải bài tập**: Guider đọc ảnh bài tập, dựng lại file Excel, giải và làm hướng dẫn trên chính bảng đó.

## Quyết định

1. Thanh chọn **Hướng dẫn | Giải bài tập** ở đầu cột chat. Ảnh (chọn, dán Ctrl+V, kéo thả, chụp cửa sổ Excel) thuộc
   chế độ Giải bài tập; dán/kéo ảnh tự chuyển sang chế độ này. Hướng dẫn giữ câu hỏi + "Dùng file của bạn".
2. **Đọc ảnh** (`vision/exercise.py`): chép bảng đầy đủ (tối đa 40 hàng × 15 cột) và các yêu cầu viết trên ảnh; bỏ
   cột số hàng ("Cột / Hàng") và chữ cột trong tiêu đề ("B (Mã NV)" → "Mã NV"); bảng đặt từ A1 như trên ảnh. Yêu
   cầu gõ thêm trong ô chat được cộng vào đề. Không có yêu cầu → hỏi lại đề bài.
3. **Giải**: model viết lời giải cho đúng bảng (ô/vùng, công thức tiếng Anh, giải thích); cột kết quả mới đặt bên
   phải bảng có tiêu đề, tổng/đếm đặt dưới bảng; không được ghi đè dữ liệu. Lời giải được **chạy thử trong một
   Excel ẩn** trên bảng dựng lại; công thức lỗi (#DIV/0!…) hoặc ghi đè → gửi lỗi cho model sửa một lần; vẫn sai thì
   báo người dùng, không làm mẫu sai.
4. **Làm mẫu** trên bảng dựng lại (tham chiếu ô chính xác, không ánh xạ): gõ tiêu đề, chọn vùng, gõ công thức,
   **Ctrl+Enter** điền cả vùng; kiểm tra COM `cell.formula_ok` ở ô đầu. Yêu cầu không phải công thức (định dạng, biểu
   đồ…) được ghi "chưa làm mẫu" trong bài. Bài có mục "Bài tập của bạn" (ảnh, đề, kết quả Excel tính được).
5. Đọc và giải dùng Gemini khi có key và chưa tắt "Đọc ảnh bằng Gemini"; không thì model trên máy.

## Số đo (10/11/2026, ảnh một bảng nhân viên)

| Bước | Thời gian |
|---|---|
| Gemini đọc ảnh, dựng bảng 5 × 8 đúng vị trí A1:H6 | 4,1 s |
| Viết lời giải + thử trong Excel ẩn (lương `=F2/26*E2`, tổng `=SUM(G2:G6)`) | 4,8 s |
| Làm mẫu 3 bước + viết bài | ~18 s |
| Tổng | 27 s |

## Hệ quả

- SPEC §11: `tutorial.create` nhận `mode` ("guide" | "exercise"); exercise cần `problem_image`.
- Luồng ảnh của ADR-0005 (chọn bài đã học theo ảnh) vẫn còn trong engine nhưng app không còn gửi ảnh ở chế độ Hướng dẫn.
- Chưa làm: bài tập Word/PowerPoint; yêu cầu không phải công thức (định dạng có điều kiện, biểu đồ, sắp xếp) trong
  chế độ Giải bài tập.
