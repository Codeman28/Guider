# Phase 1 — Nghiệm thu (22/10/2026)

Tiêu chí (SPEC §12): `kem run --task …` sinh thư mục tutorial (JSON + ảnh) cho 3 tác vụ, không LLM;
chạy 10 lần liên tiếp không lỗi, teardown sạch (không còn process/temp file).

Máy: Windows 10 Pro 19044, M365 build 20326, giao diện EN, 125% DPI, cửa sổ sandbox 1280×800 logic.

| Tác vụ | Bước | Kết quả 10 lần | Teardown sạch | Thời gian/lần |
|---|---|---|---|---|
| `pivot_basic` (PivotTable) | 3 | **10/10 ok** | 10/10 | 19–21 s |
| `chart_column` (biểu đồ cột) | 3 | **10/10 ok** | 10/10 | 16–18 s |
| `cf_greater_than` (định dạng có điều kiện) | 6 | **10/10 ok** | 10/10 | 24–28 s |

Sau 30 lần: không còn process `EXCEL.EXE`, không lần nào phải TerminateProcess (`forced=false`).
Sandbox không bao giờ được lưu nên không sinh file tạm; mỗi phiên chỉ ghi vào thư mục output của nó (`manifest.json`).

Kiểm tra thêm (1 lần, không thuộc tiêu chí): `--width 1024` → ribbon thu gọn nhóm Tables, Grounder tự chèn
bước "Mở nhóm **Tables**" và tutorial thành 4 bước, ok.

Unit test: 57 passed (`pytest`), `safety/` 100% branch coverage. `llm/sanitizer.py` chưa tồn tại (Phase 2).

## Phát hiện trong Phase 1 (đã sửa)

1. **Thứ tự khởi tạo COM:** pywinauto đặt `sys.coinit_flags=0` (MTA) khi import. Nếu pywin32 khởi tạo COM trước,
   proxy Excel báo "Object is not connected to server" sau lần quét UIA đầu → `env/runtime.py` khởi tạo theo đúng thứ tự.
2. **Excel từ chối lời gọi khi đang khởi động** (`RPC_E_CALL_REJECTED`) → mọi bước setup đều qua `com_retry`;
   setup lỗi thì tự Quit instance vừa tạo.
3. **Mẹo phím Alt để đưa cửa sổ lên trước làm hiện KeyTips trong ảnh** → bỏ; PrintWindow chụp được cửa sổ bị che (S3).
4. Nội dung popup ribbon nằm trong cây UIA của cửa sổ chính; hộp thoại (`NUIDialog`) có cây riêng → snapshot gồm cửa sổ chính + mọi cửa sổ của process sandbox.
5. Phần tử tài khoản (`MeControlWidget`) có Name là **tên thật của người dùng** → bị loại ngay ở snapshot (không vào trace),
   rect của nó chỉ dùng để che avatar trên ảnh.

## Chưa làm / giới hạn

- Toast thật (Phase 3): CLI chỉ in cảnh báo "đừng gõ phím, Esc để dừng".
- Chưa thử Esc giữa chừng và người dùng gõ chen ngang trong vòng nghiệm thu (code đã có: `_check_cancel`, `_ping_excel`).
- Nhãn tiếng Việt trong `aliases.yaml`/`blocklist.yaml` chưa kiểm chứng (chưa có máy giao diện VI).
- Chỉ Excel; ma trận DPI 100/150% chưa chạy.
