# ADR-0001: Điều chỉnh SPEC theo kết quả Phase 0

- Trạng thái: **Đã chấp nhận**
- Bằng chứng: `docs/spikes/RESULTS.md`, `docs/spikes/out/*.json`

## Quyết định

1. **Foreground (ADR-3, §6.8, §14) — từ S4.** Office tự kích hoạt cửa sổ sau mỗi lệnh ribbon gọi qua UIA pattern, kể cả khi
   cửa sổ đang ở nền. Bỏ lời hứa "người dùng làm việc song song" ở v1. Toast "đừng gõ phím, Esc để dừng" hiện từ bước đầu;
   kiểm tra chế độ Edit + retry COM trước mỗi bước; teardown gửi Esc trước khi Close. Keyboard hook lùi sang v1.5,
   desktop ảo vẫn ở v2.
2. **Whitelist (§2, §8) — từ S3.** Popup ribbon có owner là cửa sổ ẩn, không phải HWND chính. Whitelist = HWND sandbox +
   cửa sổ top-level cùng PID (Excel/Word); với PowerPoint chỉ nhận cửa sổ cùng PID xuất hiện sau hành động của Guider.
3. **Grounder (§6.5) — từ S1.** Snapshot bằng raw UIA `FindAllBuildCache`. Expand nhóm ribbon thu gọn là đường chính.
4. **Tech stack (§5).** Python 3.12.

## Hệ quả

- Phase 1 cài teardown chịu được Excel đang ở chế độ Edit và COM busy.
- Các mục S5 (100%/150%), S6 (máy giao diện VI), S7 (Ollama) vẫn mở; không chặn Phase 1 (Phase 1 không dùng LLM).
