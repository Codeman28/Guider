---
name: Guider
description: Hướng dẫn Excel chụp trên chính máy bạn — mỗi bước là một tờ lịch bloc, xé đi khi đã làm xong.
colors:
  sunday-red: "#c8102e"
  glue-red: "#8e1b1b"
  lunar-slate: "#4a5a6a"
  calendar-ink: "#1d1b19"
  sheet-white: "#fffdf9"
  calendar-paper: "#f7f4ee"
  shell: "#e9e4da"
  paper-edge: "#d8d1c4"
typography:
  display:
    fontFamily: "Oswald, Be Vietnam Pro, sans-serif"
    fontSize: "92px"
    fontWeight: 700
    lineHeight: 1
  headline:
    fontFamily: "Be Vietnam Pro, ui-sans-serif, sans-serif"
    fontSize: "28px"
    fontWeight: 700
    lineHeight: 1.25
  title:
    fontFamily: "Be Vietnam Pro, ui-sans-serif, sans-serif"
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.55
  body:
    fontFamily: "Be Vietnam Pro, ui-sans-serif, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Be Vietnam Pro, ui-sans-serif, sans-serif"
    fontSize: "14px"
    fontWeight: 500
    lineHeight: 1.55
  numeral-caption:
    fontFamily: "Oswald, Be Vietnam Pro, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    letterSpacing: "0.12em"
rounded:
  sheet: "6px"
spacing:
  tight: "8px"
  gap: "12px"
  chat-gutter: "20px"
  pane-gutter: "24px"
  step-rhythm: "24px"
  wide-gutter: "48px"
components:
  button-primary:
    backgroundColor: "{colors.calendar-ink}"
    textColor: "{colors.calendar-paper}"
    typography: "{typography.label}"
    rounded: "{rounded.sheet}"
    padding: "10px 16px"
  button-secondary:
    backgroundColor: "{colors.sheet-white}"
    textColor: "{colors.calendar-ink}"
    rounded: "{rounded.sheet}"
    padding: "6px 12px"
  button-outline:
    backgroundColor: "transparent"
    textColor: "{colors.calendar-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.sheet}"
    padding: "8px 16px"
  input-question:
    backgroundColor: "{colors.sheet-white}"
    textColor: "{colors.calendar-ink}"
    rounded: "{rounded.sheet}"
    padding: "8px 12px"
  input-question-disabled:
    backgroundColor: "{colors.shell}"
  tab-active:
    backgroundColor: "{colors.calendar-paper}"
    textColor: "{colors.calendar-ink}"
    padding: "10px 16px"
  tab-inactive:
    backgroundColor: "{colors.paper-edge}"
    textColor: "{colors.calendar-ink}"
    padding: "10px 16px"
  calendar-sheet:
    backgroundColor: "{colors.sheet-white}"
    textColor: "{colors.calendar-ink}"
    rounded: "{rounded.sheet}"
    padding: "12px 16px"
  library-cell:
    backgroundColor: "{colors.sheet-white}"
    textColor: "{colors.calendar-ink}"
    rounded: "{rounded.sheet}"
    padding: "12px"
  demo-notice:
    backgroundColor: "{colors.sheet-white}"
    textColor: "{colors.calendar-ink}"
    rounded: "{rounded.sheet}"
    padding: "10px 12px"
---

# Design System: Guider

<!-- Nguồn token duy nhất: design/tokens.json (dùng chung cho app/scripts/gen-tokens.mjs → app/src/tokens.css và engine/kem_engine/annotate/draw.py). Frontmatter này ghi lại các giá trị đó; khi đổi màu, đổi ở tokens.json trước. -->

## Overview

**Creative North Star: "Lịch bloc"**

Mỗi bước là một tờ của cuốn lịch bloc treo tường kiểu Việt Nam: một con số lớn, một việc cần làm, và tờ lịch được xé đi khi bước đó đã được xác minh. Màn hình là giấy lịch mỏng màu ngà đặt trên một lớp vỏ sẫm hơn một chút, mực đen lịch, đỏ Chủ nhật, viền keo đỏ sẫm ở mép trên của tờ đang dùng, và chữ in phụ màu xám xanh như dòng âm lịch. Hệ thống này từ chối kiểu mặc định của ứng dụng chat: nền xám, nhấn xanh dương, bong bóng tin nhắn bo tròn.

Mật độ vừa phải, đọc thong thả: cột chat hẹp 360 px bên trái, bài hướng dẫn rộng bên phải với một cột số bên cạnh nội dung. Chiều sâu chỉ đến từ mép giấy (đường viền mảnh) và chồng tờ lịch, không có bóng đổ, không gradient, không thẻ lồng thẻ. Chuyển động duy nhất có chủ ý là cú xé tờ lịch.

Ảnh chụp màn hình là nhân vật chính: chúng được hiển thị cùng một tỉ lệ cố định, trên một đường nền chung, nên giao diện xung quanh phải yên lặng, ít màu và không cạnh tranh với khung chú thích đỏ trong ảnh.

**Key Characteristics:**
- Giấy lịch ngà trên vỏ sẫm hơn; tờ đang hoạt động là giấy trắng ấm có viền keo đỏ sẫm ở mép trên.
- Con số Oswald đậm, khổng lồ, là điểm neo của mỗi bước; mọi chữ khác dùng Be Vietnam Pro.
- Đúng ba cỡ chữ cho văn bản (28 / 16 / 14 px); con số có thang riêng.
- Góc gần vuông 6 px, viền giấy mảnh, không bóng đổ, không gradient.
- Đỏ Chủ nhật hiếm và có nghĩa: cảnh báo, dừng, bước chưa làm mẫu được, và khung chú thích trong ảnh.
- Một chuyển động đặc trưng: tờ lịch bị xé khi bước được xác minh.

## Colors

Bảng màu của một tờ lịch in: giấy ngà, mực đen ấm, hai sắc đỏ có vai trò riêng và một màu xám xanh cho chữ in phụ; mọi màu trung tính lấy từ một thang tông cố định.

### Primary
- **Đỏ Chủ nhật** (sunday-red): màu nhấn duy nhất, cũng chính là `color.accent` trong tokens.json mà bộ chú thích ảnh dùng cho khung, mũi tên và huy hiệu số. Trong giao diện chỉ dùng cho: viền thông báo "đừng gõ phím — Esc để dừng", con số của bước chưa làm mẫu được, trạng thái không trọn vẹn (một phần / thất bại / đã dừng), biểu tượng chưa đạt, lời kết khi hướng dẫn không đầy đủ, và ngày Chủ nhật trên ô lịch thư viện.

### Secondary
- **Đỏ keo** (glue-red): dải keo ở mép trên của tờ lịch. Viền trên 6 px cho tờ/ô lịch (tờ bước, ô thư viện, thẻ kết quả trong chat, hộp đồng ý), 4 px cho tab đang mở và gạch dưới thanh thương hiệu. Không dùng cho chữ, nền hay nút.

### Tertiary
- **Xám âm lịch** (lunar-slate): chữ in phụ như dòng âm lịch: nhãn môi trường ("Chụp trên Excel của bạn · build … "), số giây, chú thích BƯỚC / TRÊN n / THÁNG n, mẹo, trạng thái ổn, placeholder của ô nhập.

### Neutral
- **Mực lịch** (calendar-ink): toàn bộ chữ chính, nền nút chính, viền nút viền, vòng focus, nền vùng chọn.
- **Giấy trắng tờ lịch** (sheet-white): bề mặt của mọi thứ "là một tờ": tờ bước, ô thư viện, nút phụ, ô nhập, thông báo.
- **Giấy lịch** (calendar-paper): nền của cột chat, nội dung tab và hộp đồng ý; chữ trên nút mực.
- **Vỏ** (shell): nền ngoài cùng (body, thanh tab, màn hình đồng ý), bong bóng câu hỏi trong chat, ô nhập khi bị khóa.
- **Mép giấy** (paper-edge): mọi đường viền mảnh và đường kẻ chia; nền tab không hoạt động.
- **Thang tông cố định**: 11 bậc từ `#fffdf9` đến `#1d1b19` trong tokens.json (`color.ramp`, sinh ra `--color-ramp-0..10`). Màu trung tính mới phải lấy từ thang này; hiện chỉ `ramp-5` (`#bdb5a7`) được dùng thêm, cho thanh cuộn.

### Named Rules
**The Sunday Rule.** Đỏ Chủ nhật chỉ báo điều người học cần chú ý: cảnh báo, dừng, chưa làm được, hoặc khung chú thích trong ảnh. Không bao giờ dùng để trang trí, làm nút chính hay đánh dấu trạng thái "ổn".

**The Glue Edge Rule.** Đỏ keo chỉ xuất hiện như một dải ở mép trên (4–6 px) của tờ hoặc tab đang hoạt động. Nó đánh dấu "tờ này đang được cầm", không mang nghĩa khác.

**The One Source Rule.** Màu, phông và cỡ chữ đi ra từ design/tokens.json, dùng chung cho giao diện và ảnh chú thích. Không viết hex trực tiếp trong component.

## Typography

**Display Font:** Oswald (dự phòng Be Vietnam Pro, sans-serif) — chỉ cho con số và chú thích con số
**Body Font:** Be Vietnam Pro (dự phòng ui-sans-serif, sans-serif)

**Character:** Oswald hẹp và đậm như số in trên lịch bloc; Be Vietnam Pro đầy đủ dấu tiếng Việt, rõ ràng, bình tĩnh. Cả hai phông được đóng gói cục bộ qua @fontsource, không tải từ mạng.

### Hierarchy
- **Display** (Oswald 700, 92 px, line-height 1): con số của tờ lịch đang chạy trong cột chat. Thang số riêng: 140 px ở chế độ Từng bước khi rộng ≥ 1100 px (96 px khi hẹp hơn), 96 / 72 px ở chế độ Bài đầy đủ, 48 px cho ngày trên ô thư viện, 40 px cho ba câu trên màn hình đồng ý. Bước chưa làm mẫu được thì con số chuyển sang đỏ Chủ nhật.
- **Headline** (Be Vietnam Pro 700, 28 px, line-height 1.25, text-wrap: balance): tiêu đề hướng dẫn, tiêu đề màn hình đồng ý, tiêu đề thư viện trống.
- **Title** (Be Vietnam Pro 600, 16 px): tiêu đề của từng bước và nhãn nút Office in đậm (tên UIA thật).
- **Body** (Be Vietnam Pro 400, 16 px, line-height 1.55): lời văn; đoạn văn trong bài giới hạn 680 px.
- **Label** (Be Vietnam Pro 500, 14 px): nút, tab, trạng thái, mẹo, nhật ký.
- **Numeral caption** (Oswald, 14 px, letter-spacing 0.12em, chữ in hoa, xám âm lịch): BƯỚC, TRÊN n, THÁNG n, và số giây (tabular-nums).

### Named Rules
**The Three Sizes Rule.** Văn bản chỉ có ba cỡ: 28, 16, 14 px (`--text-title`, `--text-body`, `--text-small`). Con số Oswald là một thang riêng và không bao giờ dùng cho chữ.

**The Numeral Caption Rule.** Chữ in hoa giãn cách chỉ tồn tại như chú thích gắn liền với một con số (BƯỚC trên số, TRÊN n dưới số, THÁNG n trên ngày), giống chữ in trên tờ lịch. Không dùng làm dòng dẫn phía trên tiêu đề hay nhãn mục.

**The Verbatim Label Rule.** Tên nút Office trong lời văn luôn in đậm và giữ nguyên chuỗi thật; không được cắt bớt. Chuỗi dài tiếng Việt và tên Office dài luôn xuống dòng (overflow-wrap: anywhere), không bao giờ dùng dấu "…".

## Layout

Hai cột trong một cửa sổ: cột chat cố định 360 px bên trái (giấy lịch, viền phải mảnh), khung hướng dẫn chiếm phần còn lại (vỏ, với thanh tab ở trên và nội dung giấy lịch bên dưới). Mỗi cột tự cuộn; trang không có thanh cuộn ngoài. Dưới 900 px, hai cột xếp thành một: chat ở trên (tối đa 45vh), tab ở dưới, và các câu hỏi gợi ý ẩn đi khi đã có tab.

Bài hướng dẫn rộng tối đa 1180 px, lề 24 px (48 px khi ≥ 1100 px). Mỗi bước là một lưới hai cột: cột số 96 px (150 px khi ≥ 1100 px) cạnh nội dung, khoảng cách 24 px, các bước cách nhau bằng đường kẻ mép giấy và đệm 24 px trên dưới. Ảnh chụp hiển thị ở một hệ số cố định (0,62 so với pixel vật lý) để mọi bước cùng tỉ lệ trên cùng đường nền, chỉ bị giới hạn bởi chiều rộng cột.

Nhịp khoảng cách theo bậc 4 px: 8 px giữa các phần tử sát nhau, 12 px giữa các mục danh sách, lề 20 px trong cột chat, 24 px trong khung hướng dẫn. Ô nhập câu hỏi luôn ghim ở đáy cột chat; thông báo đang làm mẫu nằm ngay trên nó.

### Named Rules
**The Shared Baseline Rule.** Mọi ảnh chụp trong một hướng dẫn dùng chung một hệ số tỉ lệ; không phóng to ảnh nhỏ cho đầy cột.

## Elevation & Depth

Hệ thống phẳng. Không có box-shadow trong giao diện. Chiều sâu đến từ ba thứ: tông giấy (vỏ → giấy lịch → giấy trắng tờ lịch), viền mép giấy 1 px, và chồng tờ lịch: dưới tờ đang chạy có một mẩu tờ kế tiếp (cao 10 px, thụt vào 4 px mỗi bên, bo góc dưới) để gợi cuốn lịch còn dày.

### Named Rules
**The Paper Edge Rule.** Không bóng đổ, không gradient. Một bề mặt tách khỏi nền bằng tông giấy và viền mảnh, không bằng bóng.

## Shapes

Góc gần vuông 6 px (`--radius-sheet`) cho mọi nút, ô nhập, ảnh chụp và thông báo. Tờ lịch và ô thư viện chỉ bo hai góc dưới, vì mép trên là dải keo phẳng. Tab có góc vuông và dải keo 4 px ở mép trên khi đang mở. Viền luôn 1 px màu mép giấy; viền mực chỉ cho nút viền, nhóm chuyển chế độ đọc và trạng thái hover. Biểu tượng là nét đơn 16 px, độ dày nét 1.75, đầu nét tròn, theo currentColor (dấu đạt, dấu chưa đạt, chờ, mũi tên trái/phải), và luôn đi kèm chữ hoặc nhãn trợ năng.

## Components

### Buttons
Rõ ràng và điềm tĩnh, như nút trên một tờ giấy in.
- **Shape:** góc gần vuông (6 px).
- **Primary:** nền mực lịch, chữ giấy lịch, Label 500; đệm 10 × 16 px trong chat và điều hướng bước, 12 × 20 px trên màn hình đồng ý. Dùng cho Hỏi, Bước tiếp, Đồng ý và kiểm tra máy / Bắt đầu.
- **Outline:** nền trong, viền mực 1 px, chữ mực 500 (Dừng, Lùi).
- **Secondary:** nền giấy trắng, viền mép giấy 1 px, 14 px (Xuất Markdown, Xuất HTML, In / lưu PDF, Xem Guider đã làm gì).
- **Hover / Focus:** hover đổi viền mép giấy sang mực; focus là vòng mực 2 px cách 2 px. Khi bị khóa, nút giảm độ mờ (40%).
- **Segmented toggle:** nhóm "Bài đầy đủ / Từng bước" chung một viền mực, mục đang chọn nền mực chữ giấy.

### Chips
- **Câu hỏi gợi ý:** nút toàn chiều rộng, nền giấy trắng, viền mép giấy, căn trái, hover viền mực. Chỉ hiện khi chat còn trống.

### Cards / Containers
- **Corner Style:** 6 px (tờ lịch: chỉ góc dưới).
- **Background:** giấy trắng trên nền giấy lịch hoặc vỏ.
- **Shadow Strategy:** không có (xem Elevation & Depth).
- **Border:** 1 px mép giấy; tờ đang có ý nghĩa thêm dải keo trên 6 px.
- **Internal Padding:** 12 × 14–16 px.
- Bong bóng câu hỏi của người dùng là khối vỏ phẳng không viền; câu trả lời văn bản không có khung.

### Inputs / Fields
- **Style:** ô nhập hai dòng, nền giấy trắng, viền mép giấy, 6 px, placeholder xám âm lịch, không đổi kích thước.
- **Focus:** vòng mực 2 px.
- **Disabled:** nền vỏ khi Guider đang làm mẫu, placeholder "Chờ Guider làm mẫu xong…".

### Navigation
- **Thanh thương hiệu:** cao 56 px, chữ "Guider" đậm, gạch dưới đỏ keo 4 px.
- **Tab:** Label 14 px; tab mở nền giấy lịch, chữ 500, dải keo 4 px trên; tab không mở nền mép giấy. Tiêu đề tab xuống dòng (tối đa 260 px), nút đóng là dấu chéo nét đơn trong cùng ô màu.
- **Điều hướng bước:** Lùi (viền) · "i / n" Oswald xám âm lịch · Bước tiếp (chính); phím ← / → đổi bước.

### Calendar Sheet (signature)
Tờ lịch của bước đang chạy trong cột chat: giấy trắng, dải keo 6 px, chú thích BƯỚC, con số 92 px, TRÊN n, hành động với tên nút in đậm, và số giây đã trôi qua. Bên dưới là mẩu tờ kế tiếp, rồi danh sách cuống các bước đã xong (dấu đạt · Bước n · hành động · số giây Oswald). Khi một bước được xác minh, tờ trên cùng bị xé: dịch lên 36 px, xoay −4°, mờ dần trong 420 ms với cubic-bezier(0.4, 0, 1, 1), điểm xoay ở góc trên trái. Với prefers-reduced-motion, tờ biến mất ngay.

### Library Cell
Lịch sử hướng dẫn là các ô lịch nguyên tờ trong lưới tự lấp (tối thiểu 180 px): THÁNG n, ngày tạo bằng con số 48 px (đỏ Chủ nhật nếu là Chủ nhật), tiêu đề, trạng thái. Hover viền mực.

### Demo Notice
Hộp giấy trắng viền đỏ Chủ nhật 1 px, chữ 14 px, nằm trên ô nhập trong suốt lúc làm mẫu: "đừng gõ phím hay bấm chuột", phím Esc, và nút viền Dừng.

## Do's and Don'ts

### Do:
- **Do** lấy mọi màu, phông và cỡ chữ từ design/tokens.json để giao diện và ảnh chú thích luôn cùng một bảng màu.
- **Do** cho mỗi bước một con số Oswald lớn kèm chú thích BƯỚC / TRÊN n, và chỉ một hành động.
- **Do** dùng dải keo đỏ sẫm (4–6 px, mép trên) để đánh dấu tờ hoặc tab đang hoạt động.
- **Do** hiển thị mọi ảnh chụp ở cùng một hệ số tỉ lệ trên cùng đường nền.
- **Do** để chuỗi tiếng Việt dài và tên nút Office dài xuống dòng thay vì cắt.
- **Do** giữ chuyển động duy nhất là cú xé tờ lịch, và tắt nó khi người dùng chọn giảm chuyển động.

### Don't:
- **Don't** dùng bóng đổ hay gradient; chiều sâu chỉ đến từ tông giấy và viền mép giấy.
- **Don't** lồng thẻ trong thẻ.
- **Don't** dùng đỏ Chủ nhật cho trang trí, nút chính hay trạng thái "ổn".
- **Don't** thêm cỡ chữ thứ tư cho văn bản; con số có thang riêng.
- **Don't** dùng chữ in hoa giãn cách làm dòng dẫn trên tiêu đề; nó chỉ là chú thích của một con số.
- **Don't** dùng Inter, Arial hay phông hệ thống; không dùng màu đen hoặc xám thuần.
- **Don't** dùng biểu tượng trang trí hay ký tự thay biểu tượng (✓ ✗ × ← →); chỉ dùng biểu tượng nét đơn 16 px đi kèm chữ.
- **Don't** quay về mặc định ứng dụng chat: nền xám, nhấn xanh dương, bong bóng tin nhắn bo tròn.
