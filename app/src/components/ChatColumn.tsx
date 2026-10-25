import { useEffect, useRef, useState } from "react";

import { useApp } from "../stores/app";
import { StepStack } from "./StepStack";

const EXAMPLES = [
  "Làm sao tạo PivotTable tổng hợp doanh số?",
  "Giữ dòng tiêu đề Excel đứng yên khi cuộn",
  "Tạo mục lục tự động trong Word",
  "Thêm hiệu ứng chuyển trang cho slide PowerPoint",
];

const STATUS: Record<string, string> = {
  ok: "Đã làm mẫu xong",
  partial: "Làm mẫu được một phần",
  failed: "Chưa làm mẫu được",
  cancelled: "Đã dừng",
};

export function ChatColumn() {
  const { chat, demo, ask, cancel, open, tabs, sourceFile, pickFile, clearFile } = useApp();
  const fileName = sourceFile?.split(/[\/]/).pop();
  const [text, setText] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // scroll only this column: scrollIntoView would also scroll the (overflow-hidden) page root
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chat.length, demo?.done.length]);
  useEffect(() => {
    if (!demo) input.current?.focus();
  }, [demo]);

  const submit = (q: string) => {
    if (!q.trim() || demo) return;
    void ask(q);
    setText("");
  };

  // Single column (< 900px): the tutorial needs the room, so examples show only before one is open.
  const showExamples = chat.length === 0 && !demo;

  return (
    <aside aria-label="Hỏi Guider" className="no-print flex max-h-[45vh] min-h-0 flex-col border-b border-edge bg-paper min-[900px]:max-h-none min-[900px]:border-b-0 min-[900px]:border-r">
      <header className="flex h-14 flex-none items-center border-b-4 border-glue px-5">
        <span className="font-bold">Guider</span>
      </header>

      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto pb-4">
        {showExamples && (
          <div className={`px-5 pt-6 ${tabs.length ? "max-[899px]:hidden" : ""}`}>
            <p>Hỏi một việc bạn muốn làm trong Excel, Word hoặc PowerPoint. Guider sẽ làm mẫu ngay trên máy bạn rồi viết hướng dẫn kèm ảnh.</p>
            <ul className="mt-4 space-y-2">
              {EXAMPLES.map((e) => (
                <li key={e}>
                  <button type="button" onClick={() => submit(e)} className="w-full rounded-sheet border border-edge bg-white px-3 py-2 text-left hover:border-ink">
                    {e}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        <ol className="space-y-3 px-5 pt-5">
          {chat.map((e, i) =>
            e.kind === "question" ? (
              <li key={i} className="rounded-sheet bg-shell px-3.5 py-2.5">
                {e.text}
              </li>
            ) : e.kind === "answer" ? (
              <li key={i}>{e.text}</li>
            ) : (
              <li key={i} className="rounded-b-sheet border border-edge border-t-[6px] border-t-glue bg-white px-3.5 py-3">
                {e.title && <p className="font-medium">{e.title}</p>}
                <p className={`text-small tabular-nums ${e.status === "ok" ? "text-lunar" : "text-sunday"}`}>
                  {STATUS[e.status] ?? e.status} · {e.steps} bước · {e.seconds} giây
                </p>
                <button type="button" onClick={() => void open(e.tutorialId)} className="mt-2 text-small font-medium underline underline-offset-4">
                  Mở hướng dẫn
                </button>
              </li>
            ),
          )}
        </ol>

        {demo && (
          <div className="mt-4">
            <StepStack demo={demo} />
          </div>
        )}
      </div>

      {demo && (
        <div role="status" className="mx-5 mb-3 flex items-start gap-3 rounded-sheet border border-sunday bg-white px-3 py-2.5 text-small">
          <p className="flex-1">
            {demo.recovered
              ? "Có phím gõ lọt vào cửa sổ mẫu — Guider đã khôi phục. Đừng gõ phím hay bấm chuột nhé."
              : "Guider đang làm mẫu — đừng gõ phím hay bấm chuột."}{" "}
            Nhấn <kbd className="font-semibold">Esc</kbd> để dừng.
          </p>
          <button type="button" onClick={() => void cancel()} className="rounded-sheet border border-ink px-3 py-1 font-medium">
            Dừng
          </button>
        </div>
      )}

      <div className="mx-5 mb-2 flex flex-none items-center gap-2 text-small">
        {sourceFile ? (
          <>
            <span className="min-w-0 flex-1 truncate" title={sourceFile}>
              Làm mẫu trên bản sao của <span className="font-medium">{fileName}</span>
            </span>
            <button type="button" disabled={!!demo} onClick={clearFile} aria-label="Bỏ chọn file" className="rounded-sheet border border-edge px-2 py-0.5 disabled:opacity-40">
              Bỏ chọn
            </button>
          </>
        ) : (
          <button type="button" disabled={!!demo} onClick={() => void pickFile()} className="underline underline-offset-4 disabled:opacity-40">
            Dùng file của bạn…
          </button>
        )}
      </div>

      <form
        className="mx-5 mb-5 flex flex-none gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          submit(text);
        }}
      >
        <label htmlFor="ask" className="sr-only">Câu hỏi</label>
        <textarea
          id="ask"
          ref={input}
          rows={2}
          value={text}
          disabled={!!demo}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit(text);
            }
          }}
          placeholder={demo ? "Chờ Guider làm mẫu xong…" : "Hỏi cách làm một việc trong Office…"}
          className="min-h-12 flex-1 resize-none rounded-sheet border border-edge bg-white px-3 py-2 placeholder:text-lunar disabled:bg-shell"
        />
        <button type="submit" disabled={!!demo || !text.trim()} className="self-end rounded-sheet bg-ink px-4 py-2.5 font-medium text-paper disabled:opacity-40">
          Hỏi
        </button>
      </form>
    </aside>
  );
}
