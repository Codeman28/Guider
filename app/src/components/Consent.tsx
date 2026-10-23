import { Check, Cross, Pending } from "../lib/icons";
import { useApp } from "../stores/app";

const SENTENCES = [
  "Khi bạn hỏi, Guider mở một file Excel, Word hoặc PowerPoint trống, tự làm mẫu từng bước, chụp riêng cửa sổ đó rồi đóng lại không lưu.",
  "Guider không mở, không đọc, không đụng tới bất kỳ file nào của bạn.",
  "Ảnh chụp và hướng dẫn chỉ nằm trên máy này, không gửi đi đâu.",
];

function Row({ title, ok, detail, pending }: { title: string; ok?: boolean; detail: string; pending: boolean }) {
  return (
    <li className="grid grid-cols-[28px_1fr] gap-2 border-t border-edge py-3">
      <span className="pt-1">
        {pending ? <Pending label="đang kiểm tra" /> : ok ? <Check label="đạt" /> : <Cross label="chưa đạt" className="text-sunday" />}
      </span>
      <div>
        <p className="font-medium">{title}</p>
        <p className="text-small text-lunar">{detail}</p>
      </div>
    </li>
  );
}

export function Consent() {
  const { check, checking, checkError, runCheck, agree } = useApp();
  const started = checking || check !== null || checkError !== null;
  const excel = check?.excel;
  const model = check?.model;

  const excelDetail = checking
    ? "Guider đang mở Excel trong vài giây để đọc phiên bản và ngôn ngữ giao diện…"
    : excel?.ok
      ? `Microsoft 365 · build ${excel.build} · giao diện ${excel.ui_lang === "vi-VN" ? "tiếng Việt" : "tiếng Anh"}`
      : (excel?.error ?? checkError ?? "Chưa kiểm tra");
  const modelDetail = checking
    ? "Đang kiểm tra model trên máy…"
    : model?.ok
      ? `Model ${model.model ?? ""} sẵn sàng, chạy ngay trên máy`
      : model?.missing?.length
        ? `Thiếu model ${model.missing.join(", ")}. Mở PowerShell và chạy: ollama pull ${model.missing[0]}`
        : (model?.error ?? "Chưa kiểm tra") + " — Guider vẫn làm mẫu được, phần lời văn sẽ dùng mẫu có sẵn.";

  return (
    <main className="grid h-full place-items-center overflow-auto bg-shell p-4">
      <section aria-labelledby="consent-title" className="w-full max-w-[620px] rounded-b-sheet border border-edge border-t-[6px] border-t-glue bg-paper px-8 py-7">
        <h1 id="consent-title" className="text-title font-bold leading-tight">
          Guider làm mẫu ngay trên Office của bạn
        </h1>
        <ol className="mt-5 space-y-3">
          {SENTENCES.map((s, i) => (
            <li key={i} className="grid grid-cols-[44px_1fr] items-baseline gap-2">
              <span className="font-num text-[40px] font-bold leading-none">{i + 1}</span>
              <span>{s}</span>
            </li>
          ))}
        </ol>

        {started && (
          <ul aria-live="polite" className="mt-6">
            <Row title="Microsoft Office" ok={excel?.ok} detail={excelDetail} pending={checking} />
            <Row title="Model trên máy" ok={model?.ok} detail={modelDetail} pending={checking} />
          </ul>
        )}

        <div className="mt-6 flex flex-wrap gap-3">
          {!excel?.ok ? (
            <button
              type="button"
              onClick={() => void runCheck()}
              disabled={checking}
              className="rounded-sheet bg-ink px-5 py-3 font-medium text-paper disabled:opacity-40"
            >
              {checking ? "Đang kiểm tra máy…" : started ? "Kiểm tra lại" : "Đồng ý và kiểm tra máy"}
            </button>
          ) : (
            <button type="button" onClick={agree} className="rounded-sheet bg-ink px-5 py-3 font-medium text-paper">
              Bắt đầu
            </button>
          )}
        </div>
        <p className="mt-4 text-small text-lunar">
          Trong lúc Guider làm mẫu, đừng gõ phím hay bấm chuột vào cửa sổ mẫu. Nhấn Esc bất cứ lúc nào để dừng. Với PowerPoint, hãy đóng PowerPoint trước khi hỏi.
        </p>
      </section>
    </main>
  );
}
