# Phase 0 — Kết quả spike (chạy thật)

Ngày chạy: 22/10/2026 · Máy dev duy nhất (1 cấu hình) · Windows 10 Pro 19044 · Python 3.12.10
(SPEC ghi 3.11 — 3.12 chạy được toàn bộ spike, đề xuất nâng lên 3.12) · Microsoft 365 16.0 build 20326
· Giao diện Office: **English** (UI LCID 1033) · Theme Office: tối · Màn hình: 125% (120 DPI).

Dữ liệu thô: `docs/spikes/out/*.json`. Ảnh chụp (`*.png`) bị `.gitignore` vì chứa avatar tài khoản thật.

| ID | Kết luận | Khớp giả định SPEC? |
|---|---|---|
| S1 | **ĐẠT** — 0,41 s (UIA FindAll có cache) | Có, kèm phát hiện về ribbon thu gọn |
| S2 | **ĐẠT có điều kiện** — PowerPoint single-instance, không có HWND qua COM | Có (rủi ro đã nêu là thật) + 1 điểm khác |
| S3 | **ĐẠT** | Có |
| S4 | **ĐẠT về chức năng, KHÁC giả định về foreground** | **KHÔNG** — xem mục S4 |
| S5 | **ĐẠT ở 125%**; 100% và 150% **chưa chạy** | Chưa đủ |
| S6 | **ĐẠT trên 1 máy (EN)**; chưa có máy VI | Chưa đủ |
| S7 | **CHƯA CHẠY** — máy chưa cài Ollama | — |

---

## S1 — UIA thấy ribbon Excel? (`spikes/s1_ribbon_uia.py`)

- pywinauto backend `uia` thấy đủ tab ribbon: Home, Insert, Draw, Page Layout, Formulas, Data, Review,
  View, Automate, Help, **và tab add-in bên thứ ba** ("Analytic Solver"). Ribbon Home còn có nhóm add-in của bên thứ ba.
- Mỗi nút có Name, ControlType, BoundingRectangle; phần lớn có **AutomationId ổn định**
  (`ChartInsertGalleryNew`, `PivotChartInsert`, `InsertNewComment`…) → Locator nên ưu tiên AutomationId (đúng §6.5).
- AccessKey có thật trong UIA, ví dụ "Recommended Charts" = `Alt, N, R` → ADR-7 khả thi.
  AcceleratorKey thường rỗng trên ribbon.
- Hiệu năng quét tab Insert:
  - pywinauto `descendants()` ngây thơ: 1,76 s lần đầu (lạnh), 0,71 s lần sau → **không ổn định quanh ngưỡng 1,5 s**.
  - Raw UIA `FindAllBuildCache` (1 lời gọi, cache Name/Type/AutomationId/Rect/AccessKey, lọc IsOffscreen=false):
    **0,41 s cho cả cửa sổ, 89 phần tử** → ĐẠT. Grounder nên dùng cách này, chỉ dùng wrapper pywinauto để hành động.
- **Phát hiện quan trọng:** ở cửa sổ 1280×800 logic (125% DPI), nhóm **Tables bị thu gọn thành một MenuItem "Tables"**;
  nút PivotTable chỉ xuất hiện sau khi expand. Đây đúng là tình huống §6.5 "group bị thu gọn" — nó xảy ra
  ngay ở kích thước cửa sổ mặc định mà SPEC đề xuất, nên luật sửa cục bộ "expand group thu gọn" là bắt buộc từ Phase 1.

## S2 — DispatchEx tạo process riêng? HWND sandbox? (`spikes/s2_instances.py`)

| App | 2 lần DispatchEx | Cách lấy HWND | Teardown |
|---|---|---|---|
| Excel | **2 process riêng** | `Application.Hwnd` (class `XLMAIN`) | sạch |
| Word | **2 process riêng** | `Document.ActiveWindow.Hwnd` (class `OpusApp`) | sạch |
| PowerPoint | **cùng 1 process** (single-instance) | **Không có qua COM** — xem dưới | sạch sau khi nhả COM ref |

- PowerPoint: `Application.HWND` và `DocumentWindow.HWND` đều trả `Member not found` (cả late- lẫn early-bound)
  trên build này. Cách đang dùng: liệt kê cửa sổ top-level class `PPTFrameClass` có tiêu đề bắt đầu bằng
  `Presentation.Name`. Cách này **yếu** (tiêu đề có thể trùng nếu người dùng cũng có "Presentation1" chưa lưu).
  Đề xuất: lấy HWND bằng cách so tập `PPTFrameClass` trước/sau `Presentations.Add()` rồi đối chiếu tiêu đề.
- PowerPoint: lần DispatchEx thứ hai gắn vào instance có sẵn → nếu người dùng đang mở file thật, sandbox
  **chung process** với file đó. Whitelist bắt buộc theo HWND, không theo PID (đúng §6.3). Teardown chỉ
  được `Quit()` khi instance do Kèm tạo **và** `Presentations.Count == 0` — đã cài như vậy.
- Word: được process riêng trên máy này (SPEC nghi có thể single-instance — không đúng ở đây).
  Một lần mở Word mất **~900 s** (các lần khác ~8 s) — nghi có hộp thoại modal (first-run/đăng nhập/khôi phục)
  chặn COM. Cần timeout + phát hiện dialog khi setup sandbox.
- Process Office **chỉ thoát khi mọi COM reference được nhả** (`del`/`CoUninitialize`); teardown phải nhả ref rõ ràng.
- Mỗi cửa sổ Office kèm 4 cửa sổ `MSO_BORDEREFFECT_WINDOW_CLASS` (viền bóng) cùng PID — bỏ qua khi chụp/whitelist.

## S3 — PrintWindow + PW_RENDERFULLCONTENT (`spikes/s3_capture.py`)

- Không bị che: ảnh 1280×800 đúng nội dung, sai khác trung bình so với chụp màn hình **1,55/255**.
- **Không có cờ** `PW_RENDERFULLCONTENT`: sai khác 21,97/255 so với có cờ → cờ là bắt buộc.
- Bị Notepad che ~1/2 cửa sổ: ảnh vẫn đúng, sai khác so với ảnh sạch **0,38/255** → ĐẠT.
- Popup (menu "Tables" thu gọn) là cửa sổ riêng class `Net UI Tool Window`, owner **không phải** HWND chính
  (owner là một cửa sổ ẩn khác của Excel) + 4 cửa sổ border-effect. Chụp từng popup bằng PrintWindow rồi
  dán theo tọa độ màn hình: sai khác so với màn hình thật **0,02/255** → ghép đúng vị trí.
- Hệ quả cho whitelist §8: "dialog/popup có owner là sandbox HWND" **không đủ** — owner của popup ribbon là
  cửa sổ ẩn. Với Excel/Word (process riêng) có thể whitelist theo PID của sandbox; với PowerPoint cần luật khác.

## S4 — UIA pattern khi cửa sổ không ở foreground (`spikes/s4_background_invoke.py`)

Mỗi hành động được thử khi một cửa sổ Notepad (do spike tạo) đang ở foreground, xác minh bằng UIA/COM:

| Intent | Pattern | Chạy được? | Foreground sau đó |
|---|---|---|---|
| select_ribbon_tab | SelectionItem.Select | Có | **Excel cướp foreground** |
| toggle (Bold) | Toggle | Có (COM: Font.Bold=True) | **Excel cướp foreground** |
| invoke (Increase Font Size) | Invoke | Có (COM: Font.Size tăng) | **Excel cướp foreground** |
| expand (nhóm Tables) | ExpandCollapse | Có | **Popup của Excel** lên foreground |
| set_value (Name Box) | Value.SetValue | Có, nhưng **không** đổi vùng chọn (cần Enter) | **Excel cướp foreground** |
| type_text, key_combo | SendInput | Theo định nghĩa cần foreground — không thử để tránh gõ nhầm | — |

**Khác giả định SPEC (ADR-3):** SPEC cho rằng ưu tiên UIA pattern sẽ "không di chuột thật" và để người dùng
làm việc song song. Thực tế pattern chạy được ở nền, nhưng **Office tự kích hoạt cửa sổ của nó** sau mỗi lệnh
ribbon. Sự cố có thật trong lần chạy đầu: khi Excel sandbox lên foreground, phím người dùng gõ ở chỗ khác lọt vào
ô A1 ("l ing o"), Excel vào chế độ Edit, COM trả `RPC_E_SERVERCALL_RETRYLATER` ("application is busy"),
teardown thất bại và để lại process mồ côi (đã đóng thủ công qua native object model, không lưu).

Hệ quả:
1. Không thể giả định người dùng gõ phím song song an toàn trong lúc demo.
2. Teardown phải chịu được Excel đang ở chế độ Edit (gửi Esc tới cửa sổ sandbox, retry COM, rồi mới Close).
3. Mọi lời gọi COM cần retry khi gặp `RPC_E_SERVERCALL_RETRYLATER`.

## S5 — Rect UIA khớp ảnh chụp (Per-Monitor V2)

- Process đặt được `PerMonitorV2` (SetProcessDpiAwarenessContext thành công trước khi import pywinauto).
- Ở **125%**: so vùng rect UIA trong ảnh PrintWindow với cùng vùng trên màn hình, độ lệch tốt nhất
  **dx=0, dy=0, sai khác 0,0** cho tab Insert và nút Recommended Charts → ĐẠT.
- **100% và 150% chưa chạy**: đổi DPI hệ thống là thay đổi cài đặt màn hình của máy người dùng, spike không tự làm.
  Cần chạy lại `s3_capture.py` sau khi đổi Scale tay (Settings → Display) hoặc trên máy khác.

## S6 — Ngôn ngữ UI Office qua COM (`spikes/s6_ui_language.py`)

- `Application.LanguageSettings.LanguageID(msoLanguageIDUI=2)` trả **1033 (en-US)** cho cả Excel, Word, PowerPoint,
  khớp với tên tab tiếng Anh thấy ở S1. Trên cùng máy, `msoLanguageIDInstall=1` và `msoLanguageIDExeMode=4` trả
  **1066 (vi-VN)** — tức ngôn ngữ cài đặt khác ngôn ngữ giao diện. Chỉ được dùng hằng số 2 (UI); đọc nhầm hằng số
  sẽ khiến Kèm tưởng ribbon là tiếng Việt.
- `Application.Version` = `16.0` (không phân biệt build M365); `Application.Build` có ở cả 3 app nhưng định dạng khác nhau
  (`20326.0` / `16.0.20326` / `20326`) → cần chuẩn hóa thành số build chính trong EnvProfile/recipe key.
- **Chưa có máy giao diện tiếng Việt** để xác nhận vế "VI" của tiêu chí.

## S7 — Model local qua Ollama (`spikes/s7_ollama_planner.py`)

**Chưa chạy.** Máy chưa cài Ollama (không có lệnh `ollama`, cổng 11434 không mở). Script đã sẵn:
10 prompt mẫu (8 tác vụ Excel + 2 out-of-scope), schema Planner bằng pydantic, đo tỷ lệ JSON hợp lệ và độ trễ.
Cần người dùng cài Ollama và chọn model để kéo về (vài GB) — không tự cài theo quy tắc an toàn.

---

## Đề xuất trước khi sang Phase 1

1. **ADR-3 / §6.8 (S4):** chấp nhận rằng cửa sổ sandbox sẽ lên foreground trong lúc demo. Thay "người dùng làm việc
   song song" bằng: toast luôn hiển thị "Đang làm mẫu — đừng gõ phím, nhấn Esc để dừng" ngay từ bước đầu;
   kiểm tra trạng thái Edit của Excel (`Application.Interactive`/`Ready` + retry COM) trước mỗi bước; teardown gửi Esc
   tới HWND sandbox trước khi Close. Phương án mạnh hơn (v1.5): low-level keyboard hook chỉ trong lúc demo,
   nuốt phím khi foreground là cửa sổ sandbox, trừ Esc. Desktop ảo (v2) vẫn là lời giải triệt để.
2. **§8 whitelist (S3):** định nghĩa lại là "HWND sandbox + cửa sổ top-level cùng PID xuất hiện sau hành động của Kèm"
   cho Excel/Word; với PowerPoint (chung process) thêm điều kiện cửa sổ xuất hiện trong khoảng thời gian hành động
   và nằm trong/ngay cạnh rect cửa sổ sandbox.
3. **§6.5 Grounder (S1):** snapshot bằng raw UIA `FindAllBuildCache`; luật expand nhóm thu gọn là đường chính, không phải ngoại lệ.
4. **§5 Tech stack:** Python 3.12 thay 3.11.
5. Còn thiếu để đóng Phase 0: S5 ở 100%/150%, S6 trên máy giao diện tiếng Việt, S7 sau khi cài Ollama.
