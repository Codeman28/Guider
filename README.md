# Guider

**Guider** là trợ lý tạo hướng dẫn Microsoft Office ngay trên máy Windows của bạn. Bạn hỏi cách làm một việc trong Excel, Word hoặc PowerPoint. Guider tự mở một file mẫu riêng, **làm mẫu từng bước thật** bằng UI Automation, chụp ảnh từng bước, đánh dấu đúng nút cần bấm, rồi viết bài hướng dẫn tiếng Việt kèm ví dụ cụ thể.

Ảnh chụp trong bài là giao diện Office trên chính máy bạn, nên nút nào ở đâu đều đúng như bạn đang thấy.

## Tính năng

### Hai chế độ

| Chế độ | Dùng khi | Guider làm gì |
|---|---|---|
| **Hướng dẫn** | Muốn biết cách làm một thao tác ("Làm sao cố định dòng tiêu đề?") | Làm mẫu trên file mẫu có sẵn, hoặc trên **bản sao** file của bạn |
| **Giải bài tập** | Có ảnh bài tập Excel (bảng + đề) | Đọc ảnh, **dựng lại đúng bảng** thành file Excel, viết lời giải theo đúng cột của bạn, chạy thử trong Excel ẩn, rồi làm mẫu trên chính bảng đó |

### Điểm chính

- **Làm mẫu thật, không đoán:** mỗi bước được bấm thật và kiểm tra kết quả qua COM (ô đã tô màu, công thức không lỗi, PivotTable đã tạo…). Bước nào không làm được thì bài ghi rõ, không vẽ ảnh sai.
- **Ưu tiên bàn phím:** với Excel, Guider gõ hàm và dùng phím tắt trước, chỉ tìm nút trên ribbon khi cần.
- **Mỗi bài có ví dụ** với dữ liệu, vùng chọn và ảnh kết quả cuối.
- **Đưa đề bài vào nhiều cách:** chọn file ảnh, dán bằng Ctrl+V, kéo thả, hoặc chụp cửa sổ Excel đang mở.
- **Thư viện bài:** tìm kiếm không cần dấu, xuất Markdown / HTML / PDF, xóa để giải phóng ổ đĩa.
- **Khu huấn luyện** (bản dành cho người phát triển): nạp sách, link, tài liệu để Guider học thêm việc mới; mỗi việc chỉ được ghi nhớ sau khi làm mẫu thành công.
- **Giao diện sáng / tối** theo cài đặt Windows.

## An toàn và quyền riêng tư

- Guider chỉ thao tác trên **Office của riêng nó** (process riêng, file mẫu không lưu). Không bao giờ chạm vào cửa sổ Office bạn đang mở.
- File của bạn luôn được làm trên **bản sao**, macro bị tắt, file gốc không đổi.
- Chạm chuột, gõ phím hoặc nhấn **Esc** là Guider dừng ngay.
- Có danh sách chặn các nút nguy hiểm (xóa, gửi, chia sẻ…) và chặn phím tắt cấp Windows.
- Ảnh chụp và bài hướng dẫn nằm trên máy. Ảnh bài tập chỉ được gửi lên Gemini để đọc khi bạn đã lưu API key Gemini; tắt được trong Cài đặt để đọc hoàn toàn trên máy.

## Yêu cầu

- Windows 10 / 11
- Microsoft 365 bản desktop (Excel, Word, PowerPoint)
- Một trong hai:
  - [Ollama](https://ollama.com) chạy trên máy (mặc định dùng `qwen3:1.7b`; `gemma3:4b` để đọc ảnh), hoặc
  - API key Gemini miễn phí từ [Google AI Studio](https://aistudio.google.com/apikey), dán vào tab **Cài đặt**

## Cài đặt

Tải bộ cài `Guider_x.y.z_x64-setup.exe` ở mục **Releases** và chạy. Bộ cài khoảng 34 MB, không cần quyền quản trị.

## Build từ mã nguồn

Cần: Python 3.12, Node.js 20+, Rust (MSVC toolchain).

```bash
# Engine (Python)
cd engine
python -m venv .venv
.venv/Scripts/pip install -e .
.venv/Scripts/python -m pytest

# Đóng gói engine thành sidecar
.venv/Scripts/python build_sidecar.py

# App (Tauri + React) và bộ cài NSIS
cd ../app
npm install
npx tauri build
```

Bộ cài nằm ở `app/src-tauri/target/release/bundle/nsis/`.

## Cấu trúc

```text
app/        Ứng dụng desktop: Tauri 2 + React + TypeScript + Tailwind
engine/     Engine Python: sandbox Office, UI Automation, chụp ảnh, lập kế hoạch, viết bài
  kem_engine/
    sandbox/       Mở Office riêng, điền file mẫu, dọn dẹp, khôi phục sau sự cố
    uia/           Đọc cây UI Automation, bấm nút
    grounding/     Tìm đúng nút theo tên (Anh/Việt), loại control, vùng chứa
    orchestrator/  Chạy từng bước, kiểm tra, chụp ảnh
    vision/        Đọc ảnh bài tập, dựng lại bảng, giải và kiểm tra lời giải
    training/      Khu huấn luyện: học thẻ việc mới từ tài liệu
    safety/        Danh sách chặn, kiểm tra cửa sổ được phép
  knowledge/       Thẻ việc (Excel, Word, PowerPoint)
  fixtures/        File mẫu dữ liệu giả
docs/       Quyết định kiến trúc (ADR), biên bản nghiệm thu từng phase
SPEC.md     Đặc tả đầy đủ
```

## Công nghệ

Tauri 2 · React · TypeScript · Tailwind CSS · Python 3.12 · pywinauto (UI Automation) · pywin32 (COM) · PrintWindow · Ollama / Gemini · Pydantic · PyInstaller · NSIS

## Giới hạn hiện tại

- Mới kiểm chứng trên Office giao diện tiếng Anh, DPI 125%.
- Chế độ Giải bài tập hiện làm bài Excel tính bằng công thức; yêu cầu định dạng hay vẽ biểu đồ trong bài tập chưa được làm mẫu.
- Bộ cài chưa ký số, nên Windows SmartScreen có thể cảnh báo lần đầu chạy.

## Tác giả

Lê Minh Huy · [@Codeman28](https://github.com/Codeman28)
