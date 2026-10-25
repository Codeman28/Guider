# ADR-0004 — Khu Huấn luyện kiểu NotebookLM: học từ file, link và tự research

Ngày: 25/10/2026 · Trạng thái: **đã duyệt**

## Bối cảnh

Viết thẻ Knowledge Pack bằng tay (dump ribbon → YAML → eval) chậm. Người dùng muốn "huấn luyện" Guider nhanh và mạnh
hơn: đưa sách/giáo trình, dán link, hoặc để Guider tự research, rồi Guider tự rút ra kiến thức và lưu gọn — giống cách
NotebookLM đọc nguồn. Đây là **một cách dạy thêm**; các cách cũ (viết thẻ tay, recipe cache tự học, ghi nhớ cách hỏi)
giữ nguyên.

## Quyết định

1. **Nguồn**: file (PDF qua pypdf, DOCX, TXT, MD), link web (trang đó + các trang cùng site được nó liên kết, tối đa
   20 trang, tôn trọng robots.txt, 1 request/giây), và **tự research** (chủ đề do người dùng đưa, hoặc để trống để AI tự
   chọn việc Office phổ biến mà kho thẻ còn thiếu) — tìm nguồn bằng Google Search của Gemini, rồi đọc như link.
2. **Model đọc**: Gemini (`gemini-3.8-flash`) nếu có API key; không có thì `qwen3:4b` trên máy (chậm). Tự research
   cần Gemini.
3. **Rút ra**: mỗi đoạn có mô tả thao tác → (a) **thẻ thao tác** (các bước bấm nút), (b) **ghi chú kiến thức** ngắn
   (1–2 câu, có trích dẫn nguồn: tên file + trang, hoặc URL). Mỗi nguồn có một tóm tắt 2–3 câu.
4. **Không bịa nút**: tên nút trong thẻ được đối chiếu với dump ribbon thật (`docs/spikes/out/ribbon_dump*.json`);
   rồi **Guider làm mẫu thử từng thẻ** trong hộp cát (máy phải để yên). Chỉ thẻ chạy đúng mới vào kho; thẻ hỏng vào
   danh sách chờ kèm lý do.
5. **Bộ nhớ gọn, tự sắp xếp**: không lưu văn bản nguồn. Lưu `engine/knowledge/<app>.learned.yaml` (thẻ đã kiểm chứng
   + từ khoá bổ sung cho thẻ có sẵn), `<app>.pending.yaml`, `notes.yaml` (ghi chú) và `training_log.json` (nguồn, mã
   băm, số liệu). Thẻ trùng các bước với thẻ có sẵn → chỉ gộp cách hỏi; ghi chú trùng ý → gộp nguồn trích dẫn.
6. **Hỏi kho kiến thức**: hỏi đáp dựa trên ghi chú + thẻ, có trích dẫn.
7. **Chỉ bản dành cho nhà phát triển**: tab "Huấn luyện" chỉ hiện khi engine chạy từ repo (`D:\kem`, không phải bản
   cài), vì kết quả ghi thẳng vào `engine/knowledge` để đẩy lên git và vào bộ cài sau.

## Thay đổi SPEC (v1.4)

- §8 "Không mạng từ engine ngoài lời gọi LLM đã cấu hình": thêm ngoại lệ — ở chế độ huấn luyện, engine tải các link
  người phát triển dán vào và các trang research tìm được.
- §7.3 sanitizer: tài liệu **huấn luyện** (không phải file của người dùng) được gửi tới Gemini khi người phát triển bật
  Gemini. File của người dùng (ADR-0003) và ảnh chụp vẫn không bao giờ được gửi.
