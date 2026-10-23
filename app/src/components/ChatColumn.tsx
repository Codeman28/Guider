import { useEffect, useRef, useState } from "react";

import { useApp } from "../stores/app";
import { StepStack } from "./StepStack";

const EXAMPLES = [
  "Làm sao tạo PivotTable tổng hợp doanh số?",
  "Cách vẽ biểu đồ cột cho bảng số liệu",
  "Giữ dòng tiêu đề đứng yên khi cuộn",
  "Tô màu các ô có giá trị lớn hơn 100",
];

const STATUS: Record<string, string> = {
  ok: "Đã làm mẫu xong",
  partial: "Làm mẫu được một phần",
  failed: "Chưa làm mẫu được",
  cancelled: "Đã dừng",
};

export function ChatColumn() {
  const { chat, demo, ask, cancel, open } = useApp();
  const [text, setText] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // braces matter: newer Chromium returns a Promise from scrollIntoView, which React would treat
    // as an effect cleanup
    end.current?.scrollIntoView({ block: "end" });
  }, [chat.length, demo?.done.length]);
  useEffect(() => {
    if (!demo) input.current?.focus();
  }, [demo]);

  const submit = (q: string) => {
    if (!q.trim() || demo) return;
    void ask(q);
    setText("");
  };

  return (
    <aside aria-label="Hỏi Guider" className="no-print flex min-h-0 flex-col border-edge bg-paper min-[900px]:border-r">
      <header className="flex h-14 flex-none items-center border-b-4 border-glue px-5">
        <span className="text-lg font-bold">Guider</span>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto pb-4">
        {chat.length === 0 && !demo && (
          <div className="px-5 pt-6">
            <p className="text-[17px]">Hỏi một việc bạn muốn làm trong Excel. Guider sẽ làm mẫu ngay trên Excel của bạn rồi viết hướng dẫn kèm ảnh.</p>
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
              <li key={i} className="border-l-4 border-ink pl-3">
                {e.text}
              </li>
            ) : (
              <li key={i} className={`rounded-sheet border border-edge bg-white px-3.5 py-3 ${e.status === "ok" ? "" : "border-l-4 border-l-sunday"}`}>
                <p className="font-medium">{STATUS[e.status] ?? e.status}{e.title ? ` · ${e.title}` : ""}</p>
                <p className="text-sm text-lunar">{e.steps} bước · {e.seconds} giây</p>
                <button type="button" onClick={() => void open(e.tutorialId)} className="mt-2 text-sm font-medium underline underline-offset-4">
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
        <div ref={end} />
      </div>

      {demo && (
        <div role="status" className="mx-5 mb-3 flex items-start gap-3 border-l-4 border-sunday bg-white px-3 py-2.5 text-sm">
          <p className="flex-1">
            {demo.recovered
              ? "Có phím gõ lọt vào cửa sổ mẫu — Guider đã khôi phục. Đừng gõ phím hay bấm chuột nhé."
              : "Guider đang làm mẫu trên Excel — đừng gõ phím hay bấm chuột."}{" "}
            Nhấn <kbd className="font-semibold">Esc</kbd> để dừng.
          </p>
          <button type="button" onClick={() => void cancel()} className="rounded-sheet border border-ink px-3 py-1 font-medium">
            Dừng
          </button>
        </div>
      )}

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
          placeholder={demo ? "Chờ Guider làm mẫu xong…" : "Hỏi Guider cách làm một việc trong Excel…"}
          className="min-h-12 flex-1 resize-none rounded-sheet border border-edge bg-white px-3 py-2 placeholder:text-muted disabled:bg-shell"
        />
        <button type="submit" disabled={!!demo || !text.trim()} className="self-end rounded-sheet bg-ink px-4 py-2.5 font-medium text-paper disabled:opacity-40">
          Hỏi
        </button>
      </form>
    </aside>
  );
}
