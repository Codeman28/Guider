import { Fragment } from "react";

/** Render the engine's minimal markup: **label** → bold (labels are real UIA names, ADR-7). */
export function Rich({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("**") && p.endsWith("**") && p.length > 4 ? (
          <strong key={i} className="font-semibold">
            {p.slice(2, -2)}
          </strong>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        ),
      )}
    </>
  );
}

/** "Bước 2: Nhấn **PivotTable**" → "Nhấn **PivotTable**" (the numeral column already says which step). */
export function stripStepPrefix(heading: string): string {
  return heading.replace(/^Bước\s+\d+\s*:\s*/, "");
}

const VERBS: Record<string, string> = {
  select_ribbon_tab: "Mở thẻ",
  invoke: "Nhấn",
  expand: "Mở",
  select_item: "Chọn",
  toggle: "Bật",
  set_value: "Nhập vào",
  select_range: "Chọn",
  type_formula: "Gõ công thức vào",
  key_combo: "Nhấn",
};

export function actionText(intent?: string, label?: string): string {
  if (!label) return "Đang tìm nút…";
  return `${VERBS[intent ?? ""] ?? "Làm"} **${label}**`;
}

export function seconds(s?: number): string {
  if (s === undefined) return "";
  return `${s.toLocaleString("vi-VN", { maximumFractionDigits: 1 })} giây`;
}
