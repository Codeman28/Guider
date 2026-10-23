# Phase 5 — Nghiệm thu đóng gói và độ bền (23/10/2026)

Tiêu chí (SPEC §12, Phase 5): bộ cài chạy được trên máy không có môi trường dev; engine đóng gói thành sidecar;
không bị Defender chặn; sau crash không để lại Office mồ côi; vẫn giữ **mỗi tutorial < 2 phút**.

## Kết quả

| Hạng mục | Kết quả |
|---|---|
| Sidecar | PyInstaller 6.22.3 onefile → `guider-engine-x86_64-pc-windows-msvc.exe` **32,3 MB**. Chạy độc lập: `system.check` 6 s, tutorial Excel thật 48 s, thoát sạch khi đóng stdin |
| Bộ cài NSIS | `Guider_0.1.0_x64-setup.exe` **33,0 MiB**; cài im lặng theo người dùng (`/S /D=D:\Apps\Guider`, không cần UAC); sau cài **40 MB** (`guider.exe` + `guider-engine.exe` + `uninstall.exe`) |
| Defender (`MpCmdRun -Scan -ScanType 3`) | **Không phát hiện mối đe dọa** — cả bộ cài và sidecar, quét lại sau lần build cuối |
| e2e trên bản đã cài | Tutorial Word "in đậm tiêu đề": **66 s**, 3 ảnh, 0 ảnh hỏng; đóng app → cả hai tiến trình engine (bootloader + con) thoát |
| Khôi phục sau crash | Giết engine giữa lúc làm mẫu PivotTable → Excel "Book1" mồ côi; mở lại app → `recover()` đóng nó, sổ `%LOCALAPPDATA%\Kem\sandboxes.json` trống. Cũng đã đóng đúng một Word mồ côi thật trong lúc chạy eval |
| Giới hạn 2 phút | Excel 20/20 (tối đa 77 s), Word 10/10 (64 s), PowerPoint 10/10 (34 s) — xem Phase 3/4 |

## Cách build lại

```bash
cd D:\kem\engine && .venv/Scripts/python build_sidecar.py      # → app/src-tauri/binaries/
cd D:\kem\app && npx tauri build                                # → src-tauri/target/release/bundle/nsis/
```
(`tauri.conf.json` khai báo `"externalBin": ["binaries/guider-engine"]`; bản release lần đầu ~12 phút.)

## Chưa làm (chờ người dùng)

- **Ký số** bộ cài: chưa có chứng chỉ → SmartScreen sẽ cảnh báo "Unknown publisher" khi người khác tải về.
- Ma trận DPI 100%/150% và Office giao diện tiếng Việt.
- Bộ cài thử vẫn nằm ở `D:\Apps\Guider`; gỡ bằng `D:\Apps\Guider\uninstall.exe`.
