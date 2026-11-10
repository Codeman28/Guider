# Guider — SPEC

> Tên sản phẩm: **Guider** (đổi từ tên làm việc "Kèm" ngày 23/10/2026). Tên kỹ thuật nội bộ (`kem`, `kem_engine`, repo `kem`) giữ nguyên.

Agent tạo tutorial ngay trên máy người dùng · Microsoft 365 desktop · Windows · Model miễn phí
Phiên bản 1.4 · 25/10/2026 (cập nhật sau Phase 0, Phase 2, phản hồi dùng thử và khu Huấn luyện; xem docs/adr/0001-phase0-findings.md, docs/adr/0002-phase2-design.md, docs/adr/0003-user-file-gemini-async-writer.md, docs/adr/0004-training-notebook.md). Chuyển từ bản đặc tả Word gốc (các mục 0–16). Sơ đồ (Hình 1–3) chỉ có trong bản Word.

## 1. Bài toán và định vị sản phẩm

Người dùng phổ thông học một thao tác trên Excel/Word/PowerPoint thường phải lên mạng đọc bài hướng dẫn kiểu Thegioididong: tiêu đề, đoạn mở đầu, rồi "Bước 1, Bước 2…" mỗi bước một ảnh chụp màn hình có khung đỏ/mũi tên. Vấn đề cốt lõi: ảnh trên mạng là giao diện của máy người viết. Phiên bản Office khác (build Microsoft 365 cập nhật liên tục), ngôn ngữ giao diện khác (Tiếng Việt vs English), độ phân giải/DPI khác, theme khác, ribbon bị thu gọn khác, khiến người học không tìm thấy nút.

Guider giải quyết bằng cách tự làm mẫu thao tác trên chính bản Office của người dùng, trong một file trống do Guider tạo ra, chụp lại từng bước, vẽ chú thích, viết hướng dẫn tiếng Việt, rồi dọn sạch. Kết quả là một tutorial hiển thị trong tab của app, trùng khớp 100% với giao diện người dùng đang thấy.

Giá trị khác biệt nằm ở chữ "của chính bạn". Mọi quyết định kỹ thuật bên dưới đều phục vụ điều này.

### Phạm vi v1

Windows 10/11, Microsoft 365 desktop (Excel trước, sau đó Word, PowerPoint). Giao diện chat box. Model miễn phí.

### Ngoài phạm vi v1 (non-goals) — có lý do

| Không làm | Lý do |
|---|---|
| macOS | Accessibility API khác hoàn toàn (AXAPI), Office for Mac khác ribbon. Làm sau khi Windows ổn định. |
| Office trên web | DOM dễ tự động hóa hơn nhưng mất đúng giá trị cốt lõi (giao diện desktop của người dùng). |
| Outlook | Chứa dữ liệu cá nhân dày đặc (mail, danh bạ); rủi ro quyền riêng tư vượt lợi ích ở v1. |
| Tutorial cài đặt/tải phần mềm (như bài "tải Excel") | Không thể làm mẫu bên trong app; và agent tuyệt đối không được tải/cài phần mềm trên máy khách. Với loại câu hỏi này, trả lời bằng văn bản, không demo. |
| Thao tác cần đăng nhập, chia sẻ, gửi, lưu lên OneDrive | Có tác dụng phụ ra ngoài máy, vi phạm nguyên tắc sandbox. |

## 2. Thuật ngữ

| Thuật ngữ | Nghĩa trong dự án |
|---|---|
| UIA (UI Automation) | API trợ năng của Windows. Mỗi nút/ô/menu là một AutomationElement có Name, ControlType, AutomationId, BoundingRectangle, AccessKey, AcceleratorKey, và các control pattern (Invoke, ExpandCollapse, Toggle, SelectionItem, Value). Đây là "xương sống" của Guider. |
| COM Automation | Object model của Office (Excel.Application, Word.Application, PowerPoint.Application). Dùng để dựng và dọn sandbox và xác minh trạng thái, KHÔNG dùng để làm các bước demo (vì COM không để lại dấu vết trên giao diện để chụp). |
| Sandbox document | File trống do Guider tạo qua COM, không bao giờ được lưu, đóng với SaveChanges=False. |
| Sandbox window whitelist | Tập HWND mà Guider được phép tương tác: cửa sổ của sandbox document + các cửa sổ top-level mới xuất hiện sau hành động của Guider (xem §8 — định nghĩa theo từng app, cập nhật sau S3). Mọi cửa sổ khác là vùng cấm. |
| EnvProfile | Hồ sơ môi trường: app, build Office, ngôn ngữ UI, DPI, theme, độ phân giải. Là một phần của cache key. |
| Plan | Danh sách bước ở dạng ý định (intent), do LLM Planner sinh ra. Chưa gắn với phần tử UI cụ thể. |
| Grounding | Ánh xạ một bước trong Plan sang đúng một AutomationElement trên giao diện thật. |
| Locator | Đường dẫn ổn định tới phần tử (chuỗi ControlType+Name/AutomationId từ cửa sổ gốc). Dùng để replay. |
| Trace | Bản ghi thực thi: các bước đã ground, locator, ảnh, kết quả verify. |
| Recipe | Trace đã xác minh thành công, lưu lại để chạy lại không cần LLM. |
| Capture | Chụp ảnh riêng cửa sổ sandbox (không chụp toàn màn hình). |
| Annotation | Vẽ khung highlight, mũi tên, số bước lên ảnh. |
| Redaction | Che các vùng có thể chứa danh tính (tên tài khoản, avatar ở thanh tiêu đề). |
| Knowledge Pack | Tài liệu tri thức ngắn, do mình biên soạn, mô tả cấu trúc ribbon/menu của từng app ở cả EN và VI. Giúp model nhỏ lập kế hoạch đúng. |
| Verifier | Bộ kiểm tra hậu điều kiện sau mỗi hành động (UIA state hoặc COM state). |

## 3. Các quyết định kiến trúc then chốt (ADR) — kèm lập luận phản biện

### ADR-1: UIA-first, không phải vision-first

Phương án bị loại: "Computer-use" kiểu chụp màn hình → model đa phương thức đoán tọa độ để click.
Lý do loại: Model miễn phí/nhỏ grounding tọa độ kém; mỗi bước tốn một lần gửi ảnh (chậm, tốn quota, và lộ ảnh màn hình ra cloud). Nghiên cứu UFO² của Microsoft Research mô tả đúng điểm yếu này: các agent dựa vào screenshot thường mong manh và gây gián đoạn người dùng, và họ giải quyết bằng cách kết hợp UIA với nhận diện thị giác, ưu tiên API gốc (COM cho Office) khi có.
Quyết định: Lấy cây UIA làm nguồn sự thật. BoundingRectangle cho tọa độ chính xác tới pixel để vẽ mũi tên, không cần model đoán. LLM chỉ làm việc trên văn bản (tên phần tử), không trên ảnh. Vision chỉ là fallback (phase sau) cho phần tử không lộ qua UIA.
Hệ quả tốt: Ảnh chụp màn hình không bao giờ rời khỏi máy → giải quyết luôn bài toán quyền riêng tư.

### ADR-2: COM dựng sandbox, UIA làm demo, COM xác minh

Tách ba vai trò. COM tạo file trống và nạp dữ liệu mẫu (nhanh, tất định). UIA thực hiện các bước mà người dùng sẽ làm (để ảnh chụp phản ánh đúng thao tác). COM đọc lại trạng thái để xác minh (ví dụ ActiveSheet.PivotTables().Count tăng lên 1).

### ADR-3: "Làm chìm" = kín đáo và tối thiểu hóa dữ liệu, KHÔNG phải ẩn hoàn toàn

Yêu cầu gốc là làm chìm để người dùng không thấy bị xâm phạm. Ẩn hoàn toàn (người dùng không biết máy đang bị điều khiển) bị loại vì ba lý do:

- Kỹ thuật: Một số thao tác cần cửa sổ ở foreground và cần focus bàn phím; nếu người dùng đang gõ ở app khác cùng lúc, input sẽ đi nhầm chỗ. Cửa sổ bị minimize thì không chụp được.
- Niềm tin: Phần mềm âm thầm điều khiển Office là hành vi giống malware; antivirus/EDR có thể chặn, và nếu người dùng phát hiện thì mất niềm tin vĩnh viễn — ngược với mục tiêu.
- Pháp lý/đạo đức: Thao tác trên máy người khác phải có sự đồng ý rõ ràng.
Quyết định — "Demo mode" kín đáo:

- Lần đầu: màn hình đồng ý một lần, giải thích bằng 3 câu: Guider sẽ mở một file trống, làm mẫu, chụp riêng cửa sổ đó, rồi xóa sạch; không đọc file nào của bạn; ảnh không rời khỏi máy.
- Khi chạy: một toast nhỏ góc màn hình "Guider đang làm mẫu… nhấn Esc để dừng", cửa sổ sandbox mở cạnh app (không phủ toàn màn hình), kết thúc thì tự đóng.
- Ưu tiên hành động qua UIA pattern (Invoke/ExpandCollapse/SelectionItem/Value) — không di chuột thật. Chỉ fallback sang click chuột thật khi bắt buộc, và lúc đó toast chuyển sang "Vui lòng không dùng chuột trong vài giây".
- **Cập nhật sau spike S4:** UIA pattern chạy được khi cửa sổ sandbox ở nền, nhưng **Office tự kích hoạt cửa sổ của nó sau mỗi lệnh ribbon** (cướp foreground). Vì vậy "người dùng làm việc song song" KHÔNG được hứa ở v1. Thay vào đó: toast hiển thị ngay từ bước đầu "Guider đang làm mẫu — đừng gõ phím, nhấn Esc để dừng"; trước mỗi bước kiểm tra Excel không ở chế độ Edit (retry COM khi gặp RPC_E_SERVERCALL_RETRYLATER); teardown gửi Esc tới HWND sandbox trước khi Close. Hướng v1.5: low-level keyboard hook chỉ trong lúc demo, nuốt phím (trừ Esc) khi foreground là cửa sổ sandbox.
- Phase sau (v2): chạy trong desktop ảo cô lập. UFO² đã có giao diện Picture-in-Picture chạy automation trong một desktop ảo riêng, xây trên hạ tầng remote desktop loopback, để người dùng và agent làm việc song song. Đây là hướng nâng cấp đúng nhưng phức tạp; không đưa vào v1.
### ADR-4: Model local mặc định, cloud miễn phí là tùy chọn

Gói miễn phí của Gemini API cho phép Google dùng dữ liệu gửi lên để cải thiện sản phẩm và người đánh giá có thể đọc input/output; gói trả phí thì không. OpenRouter có các model :free giới hạn 20 request/phút và 50 request/ngày (1.000/ngày nếu tài khoản từng nạp tối thiểu 10 credit).
Quyết định: Mặc định chạy Ollama local (không giới hạn, không lộ dữ liệu, chậm hơn). Cloud miễn phí là tùy chọn người dùng bật, và payload gửi lên chỉ gồm (a) câu hỏi, (b) tên phần tử UI đã lọc, (c) EnvProfile rút gọn. Không bao giờ gửi ảnh chụp hoặc nội dung tài liệu. Lớp provider dùng giao diện chung để đổi model trong config.

### ADR-5: Ngân sách LLM ≤ 3 lần gọi / tutorial

Phép tính: thiết kế ngây thơ gọi LLM mỗi bước (plan 1 + ground ~8 + verify ~0 + viết ~8) ≈ 17 lần/tutorial → với quota 50 request/ngày của OpenRouter chưa nạp tiền, chỉ được khoảng 2–3 tutorial/ngày. Thiết kế của Guider: 1 lần Planner + grounding tất định (fuzzy match, chỉ gọi LLM khi mơ hồ) + 1 lần Writer viết gộp mọi bước = 2 lần điển hình, 3 lần tối đa → khoảng 16–25 tutorial/ngày trên cùng quota. Recipe cache đưa chi phí lần lặp lại về 0 lần gọi.

### ADR-6: Tauri 2 + Python sidecar, giao tiếp qua stdio (không mở cổng mạng)

Tauri cho bundle nhẹ, hợp thẩm mỹ tối giản; Tauri hỗ trợ nhúng binary ngoài (sidecar) để người dùng không phải tự cài Python, và trường hợp phổ biến chính là ứng dụng Python đóng gói bằng PyInstaller. Python vì hệ sinh thái tự động hóa Windows (pywinauto, pywin32, comtypes) trưởng thành nhất.
Phản biện đã cân nhắc: FastAPI + WebSocket trên localhost dễ debug hơn, nhưng mở một cổng local có khả năng điều khiển Office là bề mặt tấn công (process khác trên máy có thể gọi vào). Chọn JSON-RPC 2.0 qua stdin/stdout (NDJSON) — chỉ tiến trình cha (Tauri) nói chuyện được với engine.
Phương án thay thế đã cân nhắc: .NET + FlaUI (UIA3 native, hiệu năng tốt hơn). Giữ làm phương án B nếu spike P0 cho thấy pywinauto quá chậm khi duyệt cây UIA của ribbon.

### ADR-7: Shortcut và nhãn nút lấy từ dữ liệu thật, không để LLM bịa

Writer chỉ được nhắc phím tắt nếu nó tồn tại trong thuộc tính AccessKey/AcceleratorKey của UIA hoặc trong Knowledge Pack đã kiểm duyệt. Nhãn nút trong hướng dẫn phải là chuỗi Name thật lấy từ UIA (đúng ngôn ngữ giao diện người dùng). Đây là cơ chế chống "hallucination" quan trọng nhất của sản phẩm.

## 4. Sơ đồ mô hình

### 4.1 Kiến trúc thành phần

Hình 1. Kiến trúc thành phần của Guider

### 4.2 Trình tự một phiên

Hình 2. Trình tự một phiên tạo tutorial

### 4.3 State machine của Orchestrator

Hình 3. State machine của Orchestrator

TEARDOWN luôn chạy (khối finally), kể cả khi crash ở giữa.

## 5. Tech stack

| Lớp | Lựa chọn | Ghi chú / lý do |
|---|---|---|
| Desktop shell | Tauri 2 (Rust) | Bundle nhẹ, sidecar, capability permissions. |
| Frontend | React + TypeScript + Vite |  |
| Styling | Tailwind CSS + Radix UI primitives | Tối giản, không dùng theme nặng. |
| State | Zustand |  |
| Font | Không chốt trước — chọn qua /impeccable typeset với ràng buộc: hỗ trợ đầy đủ dấu tiếng Việt, license cho phép nhúng (OFL), KHÔNG dùng Inter/Arial/system default (bị Impeccable xếp vào anti-pattern). Ứng viên khởi điểm để so sánh: Be Vietnam Pro. | Đóng gói font local, không gọi CDN lúc chạy. |
| Design system | Impeccable (pbakaus/impeccable, Apache-2.0) — bộ quy tắc và công cụ kiểm tra thiết kế giao diện | Bắt buộc cho mọi file UI, xem mục 9.1. |
| Engine | Python 3.12 (đã kiểm chứng ở Phase 0), đóng gói PyInstaller (onefile) làm sidecar |  |
| UIA | pywinauto (backend uia) + comtypes cho truy cập UIA thô khi cần | Phương án B: .NET + FlaUI. |
| COM | pywin32 (win32com.client.DispatchEx) |  |
| Capture | Win32 PrintWindow với cờ PW_RENDERFULLCONTENT (qua pywin32/ctypes) | Phương án B: Windows.Graphics.Capture. |
| Ảnh | Pillow (vẽ ở 2× rồi downsample để khử răng cưa) |  |
| Matching | rapidfuzz + bảng alias EN↔VI |  |
| Schema | pydantic v2 | Mọi I/O với LLM phải validate. |
| IPC | JSON-RPC 2.0 qua stdio (NDJSON) | Không mở cổng mạng. |
| LLM client | Ollama: API gốc `/api/chat` với `format` = JSON schema, `think: false`, `keep_alive` (ADR-0002 §3). Cloud (OpenRouter, Gemini): openai SDK với base_url theo provider + lớp adapter riêng | Gemini — kiểm tra docs hiện hành về OpenAI compatibility, nếu không thì dùng SDK chính thức của Google trong adapter. |
| Model local | Ollama; mặc định `qwen3:1.7b` (spike S7: nhanh nhất trên CPU, 100% JSON hợp lệ) | Cấu hình trong `config/llm.toml`; kiểm tra danh sách hiện hành trên thư viện Ollama trước khi đổi. |
| Lưu trữ | SQLite (recipes, lịch sử tutorial), ảnh trong %LOCALAPPDATA%\Kem\tutorials\ |  |
| Log | structlog JSON, không log nội dung nhạy cảm |  |
| Test | pytest, pytest-asyncio; Vitest cho frontend |  |
| Đóng gói | Tauri bundler (MSI/NSIS) + code signing | Không ký số thì SmartScreen/AV dễ chặn một app tự động hóa UI. |

## 6. Cơ chế chi tiết từng module

### 6.1 Intent Router

Đầu vào: câu hỏi tự do (VI/EN). Đầu ra: {in_scope, app, task_canonical, needs_sample_data, reason}.
Bước 1 rule-based (từ khóa: excel/bảng tính/pivot/công thức → Excel…). Bước 2 chỉ gọi LLM nếu rule không chắc — và gộp lời gọi này vào Planner (không tính thêm call).
Out-of-scope (tải/cài, đăng nhập, gửi mail, mua license, app ngoài Office) → trả lời văn bản ngắn, nói rõ vì sao không làm mẫu.

### 6.2 Env Probe (không LLM)

Thu thập: app có cài không (ProgID COM đăng ký), Application.Version, Application.Build nếu có, ngôn ngữ giao diện (qua Application.LanguageSettings.LanguageID(msoLanguageIDUI) — xác minh hằng số trong spike), DPI của monitor, theme Office (nếu đọc được), độ phân giải. Kết quả: EnvProfile.
Process engine phải đặt Per-Monitor DPI Awareness V2 ngay khi khởi động để tọa độ UIA và ảnh chụp cùng hệ pixel vật lý (kiểm chứng trong spike S5).

### 6.3 Sandbox Manager (COM)

```text
setup(app, fixture) -> SandboxHandle{app_obj, doc_obj, hwnds:set, temp_dir, created_at}
teardown(handle)    -> luôn idempotent
```

- Excel: DispatchEx("Excel.Application") (tạo instance riêng), Visible=True, Workbooks.Add(), nạp fixture (dữ liệu mẫu như bảng doanh số 20 dòng) qua Range.Value. Đặt kích thước/vị trí cửa sổ cố định (ví dụ 1280×800 logic) để ảnh đồng nhất.
- Word: Documents.Add(). PowerPoint: Presentations.Add().
- Kết quả spike S2: Excel và Word — mỗi DispatchEx là một process riêng (HWND: `Application.Hwnd` / `Document.ActiveWindow.Hwnd`). PowerPoint — single-instance, sandbox có thể chung process với file thật; không có HWND qua COM, phải tìm cửa sổ `PPTFrameClass` mới xuất hiện sau `Presentations.Add()` và đối chiếu tiêu đề. Setup sandbox phải có timeout (đã gặp Word treo ~900 s vì dialog modal).
- Fixture: thư viện fixture JSON có sẵn cho các tác vụ phổ biến; LLM chỉ được chọn fixture theo ID hoặc sinh dữ liệu giả theo schema (không dữ liệu thật).
- Teardown: gửi Esc tới HWND sandbox (thoát chế độ Edit nếu có); doc.Close(SaveChanges=False) với retry khi COM báo busy; nếu instance do Guider tạo và không còn document nào khác thì Quit(); giải phóng COM refs (process Office chỉ thoát khi mọi ref được nhả); xóa temp_dir. Chỉ xóa đường dẫn có trong session manifest do Guider tạo — không bao giờ xóa bất cứ file nào khác, kể cả file AutoRecover không chắc chắn là của sandbox.
### 6.4 Planner (LLM call #1)

Đầu vào: câu hỏi, EnvProfile rút gọn, đoạn Knowledge Pack liên quan (truy hồi theo app + từ khóa), danh sách tên các tab ribbon thực tế (lấy từ UIA, rẻ).
Đầu ra (validate bằng pydantic, retry-repair tối đa 2 lần):

```json
{
  "title": "Cách tạo PivotTable trong Excel",
  "fixture_id": "sales_table_basic",
  "preconditions": [{"type": "select_range", "ref": "A1:D21"}],
  "steps": [
    {
      "id": 1,
      "intent": "select_ribbon_tab",
      "target": {"names": ["Insert", "Chèn"], "control_type": "TabItem"},
      "expected": {"type": "tab_selected", "names": ["Insert", "Chèn"]}
    },
    {
      "id": 2,
      "intent": "invoke",
      "target": {"names": ["PivotTable"], "control_type": "Button|SplitButton",
                 "within": {"names": ["Tables", "Bảng"], "control_type": "Group"}},
      "expected": {"type": "dialog_or_pane_opened"}
    }
  ]
}
```

intent thuộc tập đóng: select_ribbon_tab | invoke | expand | select_item | toggle | set_value | type_text | key_combo | select_range(COM) | wait_for.
Không cho Planner sinh tọa độ.

**Cập nhật Phase 2 (ADR-0002 §1):** Knowledge Pack gồm các *thẻ tác vụ* đã kiểm duyệt (`engine/knowledge/excel.cards.yaml`,
tên nút lấy từ dump ribbon thật). Thứ tự quyết định kế hoạch:
1. Recipe đã lưu cho (câu hỏi/tác vụ, EnvProfile) → 0 call.
2. Câu hỏi khớp **rõ ràng** đúng một thẻ (khớp nguyên cụm hoặc mọi từ của từ khóa nhiều từ, không thẻ nào khác khớp ≥ 85,
   không phải câu hỏi khắc phục lỗi) → dùng thẻ, 0 call Planner.
3. Nhiều thẻ cùng khớp → LLM **chọn một thẻ** (schema enum id thẻ + `none`), 1 call.
4. Không thẻ nào phù hợp → LLM lập kế hoạch tự do như trên (control_type giới hạn trong tên UIA; tối đa 4 tên/target).

### 6.5 Grounder

- Snapshot cây UIA chỉ của các HWND whitelist bằng raw UIA `FindAllBuildCache` (một lời gọi, cache sẵn thuộc tính — 0,41 s ở S1; duyệt bằng wrapper pywinauto chậm và không ổn định), lọc IsOffscreen=false, IsEnabled=true, giới hạn độ sâu; tạo danh sách phẳng [{eid, name, control_type, automation_id, parent_chain, rect, patterns, access_key, accel_key}].
- Lọc theo control_type và within, chấm điểm rapidfuzz với target.names + alias EN↔VI. Nếu điểm cao nhất ≥ ngưỡng (khởi điểm 90, tune bằng eval) và cách điểm thứ hai ≥ 10 → chọn, không gọi LLM.
- Mơ hồ → gọi LLM (call #3, tối đa 1 lần/tutorial, gộp mọi bước mơ hồ còn lại vào cùng một lời gọi nếu có thể) với top-k ứng viên dạng văn bản.
- Không tìm thấy → luật sửa cục bộ: phần tử có thể nằm trong tab chưa chọn, group bị thu gọn (ribbon hẹp gom group thành nút dropdown), hoặc menu chưa mở → chèn bước tiền đề (ví dụ expand group thu gọn) rồi thử lại. **Đây là đường chính, không phải ngoại lệ:** ở S1, cửa sổ 1280×800 với DPI 125% đã gom nhóm Tables thành một MenuItem, PivotTable chỉ hiện sau khi expand. Việc ribbon co giãn theo độ rộng cửa sổ chính là lý do ảnh trên mạng khác máy người dùng — đây là tình huống bình thường, không phải lỗi.
- Kết quả: Locator (chuỗi bước từ cửa sổ gốc, ưu tiên AutomationId nếu có, rồi ControlType+Name) + rect tại thời điểm chụp.
### 6.6 Capturer

- Đảm bảo cửa sổ sandbox không minimize (restore nếu cần); vị trí/kích thước cố định.
- PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT) chụp riêng cửa sổ, kể cả khi bị che một phần. Lưu ý cờ này không được tài liệu hóa chính thức; Chromium và WebRTC dùng nó vì thiếu cờ thì không chụp đúng nội dung vẽ bằng DirectComposition. Phải kiểm chứng với Office trong spike S3; nếu thất bại → Windows.Graphics.Capture.
- Không chụp được cửa sổ đang minimize.
- Menu/dropdown/dialog là cửa sổ popup riêng: chụp và ghép theo tọa độ màn hình vào khung của cửa sổ chính (hoặc chụp vùng hợp của các HWND whitelist).
- Chụp trước hành động (để mũi tên chỉ vào nút còn chưa bấm). Với bước mở dialog, chụp thêm ảnh kết quả.
### 6.7 Annotator + Redactor

Phong cách tối giản, nhất quán:

- Khung bo góc 6px, viền 3px, màu nhấn duy nhất (cấu hình, mặc định đỏ cam #E5484D), bóng mờ nhẹ.
- Mũi tên cong ngắn từ vùng trống gần nhất chỉ vào khung; tự chọn hướng để không đè lên phần tử khác.
- Badge số bước tròn ở góc khung.
- Tùy chọn "spotlight": làm tối 35% toàn ảnh trừ vùng mục tiêu.
- Vẽ ở 2× rồi downsample; xuất WebP/PNG.
- Crop thông minh: nếu mục tiêu nhỏ, crop vùng ngữ cảnh quanh nó (giữ thanh ribbon) thay vì cả cửa sổ.
- Redaction bắt buộc: làm mờ/che vùng tên tài khoản và avatar (tìm qua UIA phần tử tài khoản trên thanh tiêu đề; nếu không tìm thấy, che vùng cố định góc phải thanh tiêu đề), thanh tiêu đề chứa tên file nếu có đường dẫn. Toàn bộ thực thi local.
### 6.8 Actuator

Thứ tự ưu tiên hành động:

- UIA pattern: InvokePattern.Invoke(), ExpandCollapsePattern, SelectionItemPattern.Select(), TogglePattern, ValuePattern.SetValue() — không di chuột.
- Bàn phím gửi tới cửa sổ sandbox đang focus (cho type_text, key_combo).
- Click chuột thật (click_input) — chỉ khi 1 và 2 không làm được; bật toast cảnh báo; kiểm tra lại cửa sổ foreground là sandbox ngay trước khi click.
Trước MỌI hành động: gọi SafetyGuard.check(action, element) (mục 8).
### 6.9 Verifier

Kiểm tra expected của bước: tab được chọn (SelectionItemPattern.IsSelected), dialog mới thuộc whitelist xuất hiện, giá trị ô đổi (COM), số PivotTable/Chart tăng (COM)… Timeout mặc định 5 s, poll 100 ms hoặc lắng nghe UIA event. Thất bại → retry ≤2 → reground ≤1 → STEP_FAILED.


Kiểm tra COM có tham số dùng `expected.type = "com_check"` với `prop` phải thuộc danh sách đóng `verify/checks.py::COM_PROPS`
(ví dụ `range.font.bold`, `window.freeze_panes`); không có chuỗi nào được eval. Không bao giờ lặp lại thao tác khi chưa kiểm
tra lại hậu điều kiện (bấm toggle hai lần là tắt). Plan có thể kèm `success_check` cấp tác vụ, kiểm tra sau bước cuối.

### 6.10 Writer (LLM call #2)

Một lời gọi duy nhất cho cả tutorial. Đầu vào là Trace đã được làm sạch: mỗi bước gồm intent, tên phần tử thật (đúng ngôn ngữ UI), phím tắt thật (nếu có), kết quả verify. Đầu ra JSON:

```json
{
  "title": "...",
  "intro": "1–2 câu: làm được gì, áp dụng cho Excel trong Microsoft 365 trên máy bạn.",
  "steps": [{"id": 1, "heading": "Bước 1: Mở thẻ **Insert**", "body": "...", "tip": null}],
  "outro": "..."
}
```

Quy tắc phong cách: tiếng Việt tự nhiên, câu ngắn, mỗi bước một hành động, nhãn nút in đậm và giữ nguyên chuỗi gốc từ UIA; không thêm bước không có trong Trace; không nhắc phím tắt ngoài dữ liệu được cấp; không nói "theo hình" nếu bước không có ảnh.
Validator hậu kỳ: mọi chuỗi in đậm trong output phải tồn tại trong tập tên phần tử của Trace; sai → yêu cầu sửa một lần, vẫn sai → thay bằng tên gốc bằng code.

### 6.11 Recipe cache

Key: hash(app, task_canonical, office_major_build, ui_lang, dpi_bucket). Value: Plan + Locators + phiên bản Knowledge Pack. Replay: tìm phần tử theo Locator; nếu hỏng ở bước nào thì regrounding cục bộ bước đó (vẫn có thể 0 LLM call nếu fuzzy match đủ). Recipe chỉ được lưu khi mọi bước verify thành công. Recipe lưu kèm văn bản Writer đã viết; khi phát lại mà các bước ground ra cùng phần tử thì dùng lại văn bản → 0 call cho cả Planner lẫn Writer (ADR-0002 §5). Không lưu ảnh của người dùng khác; recipe chỉ chứa locator văn bản, nên có thể chia sẻ giữa người dùng (phase sau) như một "kho tri thức" — đây là lợi thế mạng lưới đáng cân nhắc cho mô hình kinh doanh.

## 7. LLM layer

### 7.1 Provider abstraction

Triển khai là hàm **đồng bộ** (mỗi phiên chạy trên một worker thread vì COM/UIA đồng bộ) — ADR-0002 §2.

```python
class LLMProvider(Protocol):
    name: str
    supports_json_schema: bool
    async def complete_json(self, system: str, user: str, schema: type[BaseModel],
                            temperature: float = 0.2, max_tokens: int = 2000) -> BaseModel: ...
```

Adapter: OllamaProvider, OpenRouterProvider, GeminiProvider. Router chọn theo config + trạng thái quota (đọc header rate-limit; OpenRouter trả 429 và header X-RateLimit-* khi chạm giới hạn nền tảng). Hỗ trợ fallback chain trong config.

### 7.2 Config mẫu (config/llm.toml) — giá trị là ví dụ, phải xác minh lại

```toml
[default]
provider = "ollama"
planner_model = "<model có structured output, ví dụ họ qwen3>"
writer_model  = "<cùng model hoặc model mạnh hơn về tiếng Việt>"
[ollama]
base_url = "http://127.0.0.1:11434/v1"
[openrouter]           # tùy chọn, người dùng tự bật
enabled = false
base_url = "https://openrouter.ai/api/v1"
models = ["<id>:free", "<id-dự-phòng>:free"]
[gemini]               # tùy chọn; cảnh báo chính sách dữ liệu gói free trong UI khi bật
enabled = false
model = "<flash/flash-lite hiện hành>"
[budget]
max_llm_calls_per_tutorial = 3
```

### 7.3 Payload sanitizer (bắt buộc trước mọi lời gọi cloud)

Chỉ cho đi: câu hỏi người dùng, danh sách {eid, name, control_type}, EnvProfile rút gọn (app, ngôn ngữ, major build). Ngoại lệ (v1.4, ADR-0004): tài liệu huấn luyện do người phát triển đưa vào khu Huấn luyện được gửi tới Gemini; file của người dùng và ảnh chụp thì không bao giờ. Ngoại lệ (v1.5, ADR-0005): ảnh chụp vấn đề người dùng tự gửi đi tới Gemini để đọc khi đã lưu key Gemini — "Đọc ảnh bằng Gemini" bật mặc định theo quyết định người dùng 10/11/2026, tắt được trong Cài đặt; ô chat báo trước mỗi lần gửi ảnh; câu hỏi "Cách …" rút ra từ ảnh đi tới Planner như một câu hỏi bình thường. Loại bỏ: mọi chuỗi trông như email, tên người, đường dẫn file, nội dung ô/văn bản tài liệu, tiêu đề cửa sổ. Có unit test riêng.

### 7.4 System prompt khung (tinh chỉnh khi code)

Planner: "Bạn lập kế hoạch thao tác giao diện Microsoft 365 trên Windows. Chỉ dùng các intent trong danh sách. Không sinh tọa độ. Với mỗi target, liệt kê tên nút khả dĩ bằng cả tiếng Anh và tiếng Việt theo Knowledge Pack. Nếu tác vụ không thể làm mẫu trong một file trống, trả in_scope=false kèm lý do. Chỉ trả JSON đúng schema."
Grounder (khi mơ hồ): "Chọn đúng một eid trong danh sách ứng viên phù hợp nhất với bước sau, hoặc trả null nếu không có. Không suy diễn phần tử ngoài danh sách."
Writer: như 6.10.

## 8. Quyền riêng tư và bất biến an toàn (KHÔNG được vi phạm)

- Whitelist HWND: Engine chỉ đọc cây UIA, chụp ảnh và gửi input tới HWND cửa sổ sandbox và các cửa sổ phụ của nó. Spike S3 cho thấy popup ribbon có owner là một cửa sổ ẩn, không phải HWND chính, nên "owner là sandbox" không đủ. Định nghĩa: (Excel/Word, process riêng) cửa sổ top-level cùng PID với sandbox; (PowerPoint, chung process) cửa sổ top-level cùng PID **xuất hiện sau một hành động của Guider** trong phiên và giao/kề rect cửa sổ sandbox — cửa sổ có từ trước phiên luôn bị cấm. Bỏ qua cửa sổ `MSO_BORDEREFFECT_WINDOW_CLASS`. Phát hiện cửa sổ khác ở foreground lúc chuẩn bị gửi input → dừng, không gửi.
- File người dùng (v1.3, ADR-0003): mặc định không mở, liệt kê hay đọc tài liệu có sẵn. Chỉ khi người dùng **tự chọn một file trong app**, engine copy file đó vào `%LOCALAPPDATA%\Kem\work\<session>\` và mở **bản sao** trong sandbox (macro tắt, không cập nhật liên kết, không thêm vào file gần đây); file gốc không bao giờ được mở bằng Office hay ghi đè; bản sao bị xóa khi teardown. Không duyệt cây UIA của cửa sổ khác (kể cả để "tham khảo").
- Blocklist hành động: không bao giờ invoke các phần tử thuộc nhóm File/Backstage → Account, Share, Save/Save As/Export tới vị trí ngoài temp, Send/Email, Sign in/out, Options → Trust Center, Add-ins store, Macro/VBA, Copilot. Danh sách lưu trong safety/blocklist.yaml (EN+VI), có test.
- Không mạng từ engine ngoài lời gọi LLM đã cấu hình. Ngoại lệ (v1.4, ADR-0004): ở chế độ huấn luyện (chỉ bản nhà phát triển), engine tải link người phát triển dán và trang research tìm được (tôn trọng robots.txt, giới hạn số trang).
- Ảnh chụp vấn đề (v1.5, ADR-0005): chỉ nhận ảnh người dùng tự chọn, dán (Ctrl+V) hoặc bấm "Chụp cửa sổ Office" (PrintWindow, chỉ chụp, không bấm hay gõ vào cửa sổ của người dùng). Ảnh được copy (thu nhỏ) vào `%LOCALAPPDATA%\Kem\work\`, đọc bằng Gemini (khi có key và chưa tắt) hoặc model gemma3:4b trên máy, OCR của Windows là đường lui cuối; ảnh gốc không bị đổi. Bảng nhìn thấy trên ảnh có thể được dựng lại thành file mẫu trong sandbox (không lưu ra đĩa).
- Ảnh và trace ở local. Không upload ảnh (trừ ngoại lệ ảnh vấn đề ở §7.3). Không telemetry mặc định; nếu có telemetry sau này thì opt-in và chỉ số liệu ẩn danh.
- Teardown đảm bảo trong finally; Esc toàn cục hủy ngay và teardown.
- Đồng ý một lần, minh bạch luôn: màn hình consent lần đầu; toast khi chạy; nút "Xem Guider đã làm gì" mở trace.
- Chỉ xóa đường dẫn trong session manifest.
## 9. Hiển thị tutorial (UI/UX tối giản)

Bố cục hai cột: trái là chat (hẹp, 360px), phải là vùng tab. Mỗi tutorial là một tab có tiêu đề ngắn. Nội dung tab theo cấu trúc giống bài hướng dẫn quen thuộc: tiêu đề, đoạn mở đầu, rồi từng khối "Bước n" gồm heading, ảnh có chú thích, đoạn mô tả, tip tùy chọn. Thêm hai thứ bài trên mạng không có: nhãn nhỏ "Chụp trên Excel của bạn ·  · <ngôn ngữ>" ở đầu tab, và chế độ "Từng bước" (một bước một màn hình, nút Tiếp/Lùi) cho người học chậm.
Typography: một font, ba cỡ chữ; màu nền trắng ngà / xám than (dark mode); một màu nhấn trùng màu khung chú thích. Không icon thừa, không gradient.
Xuất: Markdown + ảnh, HTML một file (ảnh base64), PDF.
Trạng thái lỗi: bước thất bại hiển thị "Bước này Guider chưa làm mẫu được trên máy bạn" + mô tả văn bản, thay vì ảnh sai.

### 9.1 Quy trình thiết kế bắt buộc: Impeccable

Mọi thay đổi trong app/src/ (UI) phải đi qua skill Impeccable. Impeccable là bộ hướng dẫn thiết kế cho AI coding agent gồm một skill, 24 lệnh và 61 luật phát hiện tất định cho giao diện do AI sinh ra.

Cài đặt (chạy ở gốc repo, một lần, trước Phase 3):

```bash
npx impeccable install --scope=project
npx impeccable telemetry off
```

Thêm khối # impeccable-ignore-start … # impeccable-ignore-end từ README của Impeccable vào .gitignore; commit .impeccable/config.json, .impeccable/design.json, .impeccable/surfaces/*.md, .impeccable/critique/*.md.

Vì sao tắt telemetry: khi bắt đầu một thiết kế mới, skill gọi roll API ở impeccable.style và mặc định gửi bản ghi ẩn danh về lựa chọn; tên dự án, code và PRODUCT.md không bị gửi. Rủi ro thấp, nhưng một sản phẩm lấy quyền riêng tư làm lời hứa cốt lõi nên giữ kỷ luật này ngay từ máy dev.


Trình tự trong Phase 3:

- /impeccable init — Impeccable sẽ ghi PRODUCT.md. Nguồn sự thật cho file này là mục 1, 8, 9 của SPEC.md (đối tượng: người dùng phổ thông Việt Nam học Office; giọng: rõ, bình tĩnh, tôn trọng quyền riêng tư; thẩm mỹ: tối giản). Không để PRODUCT.md mâu thuẫn với SPEC.
- /impeccable shape cho 3 bề mặt: chat, tutorial tab, màn hình consent lần đầu — trước khi viết component.
- Build code-first (app screen và tài liệu được Impeccable build theo hướng code-first).
- /impeccable harden — bắt buộc vì nội dung tiếng Việt dài, nhãn nút Office tràn chữ, trạng thái lỗi/hủy giữa chừng.
- /impeccable onboard cho consent + empty state của thư viện tutorial.
- Trước mỗi lần merge UI: /impeccable audit và npx impeccable detect app/src --json không còn finding chính (exit code 0).
- /impeccable document sinh DESIGN.md khi UI ổn định.
Đồng bộ token với ảnh chú thích: Annotator (Python/Pillow, mục 6.7) nằm ngoài tầm Impeccable nhưng phải dùng cùng token màu nhấn, bán kính bo góc, độ dày viền với UI. Nguồn token duy nhất: design/tokens.json, được frontend và annotate/ cùng đọc. Màu nhấn #E5484D ở mục 6.7 chỉ là giá trị tạm, chốt lại qua /impeccable colorize. Không dùng đen/xám thuần (luôn pha sắc), không lồng card trong card, không gradient tím-xanh — đều là anti-pattern Impeccable cấm.

## 10. Cấu trúc repo

```text
kem/
├─ SPEC.md
├─ app/                         # Tauri 2 + React
│  ├─ src/ (components/, stores/, rpc/, views/)
│  └─ src-tauri/ (tauri.conf.json, capabilities/, binaries/)
├─ engine/                      # Python sidecar
│  ├─ kem_engine/
│  │  ├─ rpc/            # JSON-RPC stdio server
│  │  ├─ orchestrator/   # state machine
│  │  ├─ intent/
│  │  ├─ env/            # EnvProfile, DPI
│  │  ├─ sandbox/        # excel.py, word.py, powerpoint.py
│  │  ├─ uia/            # snapshot, locator, actuator
│  │  ├─ grounding/
│  │  ├─ capture/        # printwindow.py, compose_popups.py
│  │  ├─ annotate/       # draw.py, redact.py
│  │  ├─ verify/
│  │  ├─ llm/            # providers/, sanitizer.py, prompts/
│  │  ├─ writer/
│  │  ├─ recipes/        # sqlite store
│  │  └─ safety/         # guard.py, blocklist.yaml
│  ├─ knowledge/         # excel.vi.md, excel.en.md, aliases.yaml
│  ├─ fixtures/          # sales_table_basic.json, ...
│  └─ tests/
├─ spikes/                      # Phase 0 scripts
├─ eval/                        # tasks.yaml, runner.py, reports/
└─ docs/ (spikes/RESULTS.md, adr/)
```

## 11. Hợp đồng JSON-RPC (rút gọn)

| Method | Params | Result / Notification |
|---|---|---|
| env.probe | {} | EnvProfile |
| tutorial.create | {query, app_hint?, source_file?, problem_image?, mode?} — mode "exercise" (ADR-0006): đọc ảnh bài tập, dựng lại bảng, giải và làm mẫu trên bảng đó | {session_id}; sau đó notification tutorial.progress {session_id, state, step_i, n_steps, message}, tutorial.done, và (v1.3) tutorial.updated {tutorial_id} khi Writer LLM chạy nền viết xong |
| tutorial.cancel | {session_id} | {ok} |
| tutorial.get | {tutorial_id} | Tutorial |
| tutorial.list | {} | [TutorialMeta] |
| tutorial.export | {tutorial_id, format: md\|html\|pdf} | {path} |
| settings.get/set |  | provider, model, màu nhấn, ngôn ngữ đầu ra |
| settings.set_api_key | {provider, key} | {ok} — key lưu bằng DPAPI, không bao giờ trả về qua RPC (v1.3) |
| problem.prepare / problem.paste / problem.capture | {path} / {data_b64} / {hwnd?} | {path} của ảnh PNG trong thư mục work (v1.5, ADR-0005) |
| problem.warm_up | {} | {ok} — nạp sẵn model đọc ảnh khi người dùng vừa gắn ảnh |

## 12. Lộ trình theo phase và tiêu chí nghiệm thu

### PHASE 0 — Spikes (bắt buộc làm trước, ghi kết quả thật)

| ID | Câu hỏi cần trả lời | Đạt khi |
|---|---|---|
| S1 | pywinauto (uia) có thấy các nút ribbon Excel M365 với Name, BoundingRectangle, pattern không? Duyệt cây ribbon mất bao lâu? | Liệt kê được nút trong tab Insert < 1,5 s |
| S2 | DispatchEx với Excel/Word/PowerPoint tạo process riêng hay dùng chung? Lấy HWND cửa sổ sandbox thế nào? | Có hàm trả đúng HWND sandbox cho cả 3 app, có ghi chú hành vi single-instance |
| S3 | PrintWindow + PW_RENDERFULLCONTENT chụp Excel đúng nội dung khi bị che một phần? Popup/menu? | Ảnh không đen/trắng, popup ghép đúng vị trí |
| S4 | InvokePattern.Invoke() trên nút ribbon có chạy khi cửa sổ không ở foreground? | Ghi rõ intent nào cần foreground |
| S5 | Với DPI 100/125/150%, rect UIA khớp ảnh chụp tới ±2 px sau khi đặt Per-Monitor V2? | Khung vẽ khớp nút ở cả 3 mức DPI |
| S6 | Đọc ngôn ngữ UI Office qua COM được không? | Trả đúng EN/VI trên 2 máy cấu hình khác nhau |
| S7 | Model local nào qua Ollama trả JSON đúng schema Planner ổn định nhất trên máy cấu hình phổ thông? | Bảng so sánh tỷ lệ JSON hợp lệ / độ trễ trên 10 prompt mẫu |

### PHASE 1 — Engine CLI, Excel, plan viết tay

kem run --task pivot_basic sinh ra thư mục tutorial (JSON + ảnh) cho 3 tác vụ: tạo PivotTable, chèn biểu đồ cột, định dạng có điều kiện. Không LLM. Nghiệm thu: chạy 10 lần liên tiếp không lỗi, teardown sạch (không còn process/temp file).

### PHASE 2 — LLM Planner/Grounder/Writer + Recipe cache

Nghiệm thu trên bộ eval 20 tác vụ Excel: ≥ 80% hoàn thành đủ bước; trung bình ≤ 2,5 LLM call/tutorial; replay từ cache 0 call.


Kết quả 23/10/2026 (`docs/phase2/ACCEPTANCE.md`): lượt đầu 18/20 (90%), 1,10 LLM call/tutorial, replay 0 call — **đạt**.
Điều kiện đo: máy để yên (người dùng thao tác làm menu Office tự đóng — ADR-0001 §1).

### PHASE 3 — App Tauri: chat + tutorial tab + export

Nghiệm thu: luồng end-to-end từ câu hỏi tới tab hiển thị; Esc hủy được; consent lần đầu.

### PHASE 4 — Word, PowerPoint

Mỗi app 10 tác vụ eval, ≥ 75%.

### PHASE 5 — Hardening

Installer ký số, kiểm tra với Windows Defender, crash recovery, eval trên máy giao diện tiếng Việt và tiếng Anh, 3 mức DPI.

## 13. Đánh giá (eval)

eval/tasks.yaml: mỗi tác vụ có query (VI, có biến thể diễn đạt), app, success_check (COM assertion), max_steps.
Chỉ số: tỷ lệ hoàn thành tác vụ; độ chính xác grounding từng bước; số LLM call; thời gian/tutorial; tỷ lệ chuỗi in đậm hợp lệ trong Writer (mục tiêu 100%); điểm người đọc (1–5) do 3 người chấm trên 10 tutorial ngẫu nhiên mỗi phase.
Ma trận môi trường: {EN, VI} × {100%, 125%, 150% DPI} × {cửa sổ rộng, hẹp (ribbon co lại)}.

## 14. Rủi ro và cách xử lý

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Ribbon Office đổi giữa các build | Cao | Recipe key theo build; regrounding cục bộ; Knowledge Pack có version. |
| Phần tử không lộ qua UIA (canvas, gallery) | Trung bình | Fallback COM cho bước đó + mô tả văn bản; phase sau thêm vision local. |
| Single-instance app chung process với file thật | Cao | Whitelist theo HWND (S2), Safety Guard kiểm tra foreground. |
| AV/EDR chặn | Trung bình | Code signing, không ẩn cửa sổ, không inject process. |
| Model local yếu tiếng Việt | Trung bình | Writer prompt có ví dụ mẫu; validator nhãn; cho phép người dùng bật cloud cho riêng Writer (payload đã sanitize). |
| Quota free cạn | Trung bình | Local mặc định, recipe cache, ngân sách 3 call. |
| Người dùng thao tác chen ngang | **Cao** (đã xảy ra ở S4) | Office cướp foreground sau mỗi lệnh ribbon; toast "đừng gõ phím" từ đầu; kiểm tra chế độ Edit + retry COM; teardown gửi Esc; v1.5: keyboard hook trong lúc demo. |

## 15. Quy tắc triển khai

- Không bịa API, tên hằng số, model ID hay giới hạn quota. Khi không chắc, viết spike để kiểm chứng hoặc ghi TODO(verify) kèm link docs cần đọc.
- Code chạm Windows API phải nằm sau interface để test được trên CI bằng fake; test tích hợp thật đánh dấu @pytest.mark.windows_office.
- Trong lúc phát triển, mọi script tự động hóa chỉ được chạy trên sandbox document; không bao giờ attach vào cửa sổ Office có sẵn của dev.
- Mỗi module có unit test; safety/ và llm/sanitizer.py phải đạt 100% branch coverage.
- Mọi output LLM đi qua pydantic; không eval, không thực thi chuỗi do LLM sinh.
- Commit nhỏ, mỗi phase một nhánh; cập nhật docs/adr/ khi thay đổi quyết định trong SPEC.
- Khi kết quả spike mâu thuẫn với SPEC, cập nhật SPEC (mục liên quan) sau khi được duyệt.
- Không viết hay sửa bất kỳ file UI nào khi skill Impeccable chưa được cài và PRODUCT.md chưa tồn tại. Nếu Impeccable gợi ý điều trái với SPEC (ví dụ hiệu ứng, telemetry, gọi CDN), SPEC thắng; ghi lại xung đột vào docs/adr/.
## 16. Tài liệu tham khảo (đã kiểm tra ngày 22/10/2026)

- UFO²: The Desktop AgentOS — Microsoft Research: https://www.microsoft.com/en-us/research/publication/ufo2-the-desktop-agentos/ · arXiv 2504.14603: https://arxiv.org/html/2504.14603v2
- pywinauto — Getting Started (backend uia/win32): https://pywinauto.readthedocs.io/en/latest/getting_started.html
- UI Automation — Invoke a control: https://learn.microsoft.com/en-us/previous-versions/dotnet/netframework-4.0/ms747211(v=vs.100) · AutomationElementIdentifiers: https://learn.microsoft.com/dotnet/api/system.windows.automation.automationelementidentifiers
- PrintWindow + PW_RENDERFULLCONTENT (Chromium): https://chromium.googlesource.com/chromium/src/+/d4afc97b7/ui/snapshot/snapshot_win.cc · WebRTC commit: https://webrtc.googlesource.com/src/+/f89110d67902e787f6745ad2b52f7f09fc808512
- Tauri 2 — Embedding External Binaries (sidecar): https://v2.tauri.app/develop/sidecar
- OpenRouter — API limits: https://openrouter.ai/docs/api/reference/limits
- Gemini API — rate limits: https://ai.google.dev/gemini-api/docs/rate-limits · Gemini API Additional Terms: https://ai.google.dev/gemini-api/terms
- Ollama: https://github.com/ollama/ollama · tool calling: https://docs.ollama.com/capabilities/tool-calling
- Impeccable (design skill cho AI agent, Apache-2.0): https://github.com/pbakaus/impeccable · docs: https://impeccable.style