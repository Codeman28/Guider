import { useEffect, useRef, useState } from "react";

import { useImage } from "../lib/images";
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

function Thumb({ path, alt, className }: { path: string; alt: string; className: string }) {
  const url = useImage("problem.image", { path });
  return url ? <img src={url} alt={alt} className={className} /> : <span className={`${className} bg-shell`} aria-label={alt} />;
}

export function ChatColumn() {
  const { chat, demo, ask, cancel, open, tabs, sourceFile, pickFile, clearFile, problemImage, attaching, pickImage, pasteImage, captureOffice, clearImage, settings, dragging, notice, chatMode, setChatMode } = useApp();
  const exercise = chatMode === "exercise";
  const cloudVision = settings?.vision_cloud !== false && !!settings?.has_key?.gemini; // on by default (10/11/2026)
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
    if (demo || attaching) return;
    if (exercise ? !problemImage : !q.trim()) return;
    void ask(q);
    setText("");
  };

  // Single column (< 900px): the tutorial needs the room, so examples show only before one is open.
  const showExamples = chat.length === 0 && !demo;

  return (
    <aside aria-label="Hỏi Guider" className="no-print flex max-h-[45vh] min-h-0 flex-col border-b border-edge bg-paper min-[900px]:max-h-none min-[900px]:border-b-0 min-[900px]:border-r">
      <header className="flex h-14 flex-none items-center gap-3 border-b-4 border-glue px-5">
        <span className="font-bold">Guider</span>
        <div role="group" aria-label="Chế độ" className="ml-auto flex overflow-hidden rounded-sheet border border-ink text-small">
          {(["guide", "exercise"] as const).map((m) => (
            <button key={m} type="button" aria-pressed={chatMode === m} disabled={!!demo} onClick={() => setChatMode(m)}
              className={`px-3 py-1 font-medium disabled:opacity-40 ${chatMode === m ? "bg-ink text-paper" : "bg-white"}`}>
              {m === "guide" ? "Hướng dẫn" : "Giải bài tập"}
            </button>
          ))}
        </div>
      </header>

      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto pb-4">
        {showExamples && exercise && (
          <div className={`px-5 pt-6 ${tabs.length ? "max-[899px]:hidden" : ""}`}>
            <p>Gửi ảnh bài tập Excel: bảng dữ liệu, kèm đề bài trong ảnh hoặc gõ vào ô bên dưới.</p>
            <p className="mt-2 text-small text-lunar">
              Guider đọc ảnh, dựng lại đúng bảng đó thành file Excel, tự giải (công thức theo đúng cột của bạn), thử lời giải trong Excel rồi làm mẫu từng bước ngay trên bảng ấy.
            </p>
            <p className="mt-2 text-small text-lunar">Bấm "Gửi ảnh bài tập…", kéo thả ảnh vào đây, hoặc dán bằng Ctrl+V.</p>
          </div>
        )}
        {showExamples && !exercise && (
          <div className={`px-5 pt-6 ${tabs.length ? "max-[899px]:hidden" : ""}`}>
            <p>Hỏi cách làm một thao tác trong Excel, Word hoặc PowerPoint. Guider sẽ làm mẫu ngay trên máy bạn rồi viết hướng dẫn kèm ảnh.</p>
            <p className="mt-2 text-small text-lunar">Có bài tập cần giải trên bảng của bạn? Chuyển sang <span className="font-medium">Giải bài tập</span>.</p>
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
                {e.image && <Thumb path={e.image} alt="Ảnh vấn đề bạn gửi" className="mb-2 max-h-32 rounded-sheet border border-edge" />}
                {e.text}
              </li>
            ) : e.kind === "answer" ? (
              <li key={i}>{e.text}</li>
            ) : (
              <li key={i} className="rounded-b-sheet border border-edge border-t-[6px] border-t-glue bg-white px-3.5 py-3">
                {e.title && <p className="font-medium">{e.title}</p>}
                <p className={`text-small tabular-nums ${e.status === "ok" ? "text-lunar" : "text-sunday"}`}>
                  {STATUS[e.status] ?? e.status}, {e.steps} bước trong {e.seconds} giây
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
              ? "Có phím gõ lọt vào cửa sổ mẫu; Guider đã khôi phục. Đừng gõ phím hay bấm chuột nhé."
              : "Guider đang làm mẫu."}{" "}
            Di chuột, bấm chuột, gõ phím hoặc nhấn <kbd className="font-semibold">Esc</kbd> là Guider dừng ngay.
          </p>
          <button type="button" disabled={demo.stopping} onClick={() => void cancel()} className="rounded-sheet border border-ink px-3 py-1 font-medium disabled:opacity-40">
            {demo.stopping ? "Đang dừng…" : "Dừng"}
          </button>
        </div>
      )}

      {dragging && (
        <div role="status" className="mx-5 mb-2 flex-none rounded-sheet border-2 border-dashed border-ink bg-white px-3 py-4 text-center font-medium">
          Thả ảnh bài tập (hoặc file Excel, Word, PowerPoint) vào đây
        </div>
      )}

      {notice && !demo && (
        <p role="alert" className="mx-5 mb-2 flex-none text-small text-sunday">
          {notice}
        </p>
      )}

      {exercise && (problemImage || attaching) && (
        <div className="mx-5 mb-2 flex flex-none items-center gap-3 rounded-sheet border border-edge bg-white p-2 text-small">
          {problemImage ? (
            <Thumb path={problemImage} alt="Ảnh bài tập sẽ gửi cho Guider" className="h-14 w-20 rounded-sheet border border-edge object-cover object-left-top" />
          ) : (
            <span className="h-14 w-20 rounded-sheet border border-edge bg-shell" aria-hidden />
          )}
          <span className="min-w-0 flex-1">{attaching ? "Đang lấy ảnh…" : cloudVision ? "Guider sẽ gửi ảnh này lên Gemini (Google) để đọc bảng và đề. Tắt trong Cài đặt nếu ảnh có thông tin riêng tư." : "Guider sẽ đọc ảnh này ngay trên máy (không gửi đi); có thể mất 1–2 phút."}</span>
          {problemImage && (
            <button type="button" disabled={!!demo} onClick={clearImage} aria-label="Bỏ ảnh" className="rounded-sheet border border-edge px-2 py-0.5 disabled:opacity-40">
              Bỏ ảnh
            </button>
          )}
        </div>
      )}

      <div className="mx-5 mb-2 flex flex-none flex-wrap items-center gap-x-4 gap-y-1 text-small">
        {exercise ? (
          <>
            <button type="button" disabled={!!demo || attaching} onClick={() => void pickImage()} className="underline underline-offset-4 disabled:opacity-40">
              Gửi ảnh bài tập…
            </button>
            <button type="button" disabled={!!demo || attaching} onClick={() => void captureOffice()} title="Chụp cửa sổ Excel đang mở của bạn (chỉ chụp ảnh, không bấm gì)" className="underline underline-offset-4 disabled:opacity-40">
              Chụp cửa sổ Excel đang mở
            </button>
          </>
        ) : sourceFile ? (
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
          onPaste={(e) => {
            const item = [...e.clipboardData.items].find((it) => it.type.startsWith("image/"));
            const f = item?.getAsFile();
            if (f) {
              e.preventDefault();
              void pasteImage(f);
            }
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit(text);
            }
          }}
          placeholder={demo ? "Chờ Guider làm mẫu xong…" : exercise ? (problemImage ? "Đề bài / yêu cầu (nếu ảnh chưa ghi)…" : "Gửi ảnh bài tập trước, rồi gõ đề bài nếu cần…") : "Hỏi cách làm một thao tác trong Office…"}
          className="min-h-12 flex-1 resize-none rounded-sheet border border-edge bg-white px-3 py-2 placeholder:text-lunar disabled:bg-shell"
        />
        <button type="submit" disabled={!!demo || attaching || (exercise ? !problemImage : !text.trim())} className="self-end rounded-sheet bg-ink px-4 py-2.5 font-medium text-paper disabled:opacity-40">
          Hỏi
        </button>
      </form>
    </aside>
  );
}
