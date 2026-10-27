import { useState } from "react";

import { Cross } from "../lib/icons";
import { useApp } from "../stores/app";

const APP_NAME: Record<string, string> = { excel: "Excel", word: "Word", powerpoint: "PowerPoint" };
const KIND: Record<string, string> = { file: "File", link: "Link", research: "Research" };

function SourceRow({ s }: { s: { kind: string; name: string; date: string; summary: string; added: number; merged: number; pending: number; notes: number } }) {
  return (
    <li className="border-t border-edge py-3">
      <p className="font-medium">
        <span className="mr-2 text-small text-lunar">{KIND[s.kind] ?? s.kind}</span>
        {s.name}
      </p>
      {s.summary && <p className="mt-1 text-small">{s.summary}</p>}
      <p className="mt-1 text-small tabular-nums text-lunar">
        {s.date}: {s.added} việc mới, {s.merged} gộp vào việc có sẵn, {s.pending} chờ xem, {s.notes} ghi chú
      </p>
    </li>
  );
}

export function Training() {
  const { train, trainJob, trainLast, trainMemory, trainAnswer, asking, startTraining, pickTrainingFile, cancelTraining, removeLearned, askKnowledge, demonstrateNow, setDemonstrateNow } = useApp();
  const [link, setLink] = useState("");
  const [topic, setTopic] = useState("");
  const [question, setQuestion] = useState("");
  const busy = !!trainJob;
  const p = trainJob?.progress;
  const apps = trainMemory ? Object.entries(trainMemory.apps) : [];
  const learned = apps.reduce((n, [, a]) => n + a.cards.length, 0);

  return (
    <section aria-labelledby="train-title" className="mx-auto max-w-[760px] px-8 py-8">
      <h2 id="train-title" className="text-title font-bold leading-tight">
        Huấn luyện
      </h2>
      <p className="mt-2 text-small text-lunar">
        Đưa sách, giáo trình, link hoặc để Guider tự research. Guider đọc hết, rút ra việc làm được kèm các bước, tự làm mẫu thử từng việc trong Office, rồi chỉ lưu bản tóm gọn đã kiểm chứng (không lưu nguyên văn). Model đang dùng:{" "}
        <span className="font-medium text-ink">{train?.model}</span>
        {train && !train.cloud && " (trên máy, chậm; nhập key Gemini ở tab Cài đặt để nhanh hơn)"}.
      </p>

      <div className="mt-6 grid gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" disabled={busy} onClick={() => void pickTrainingFile()} className="rounded-sheet bg-ink px-4 py-2 font-medium text-paper disabled:opacity-40">
            Tải file lên…
          </button>
          <button type="button" disabled={busy} onClick={() => void pickTrainingFile(true)} className="rounded-sheet border border-ink px-4 py-2 font-medium disabled:opacity-40">
            Chọn thư mục…
          </button>
          <span className="text-small text-lunar">PDF, DOCX, TXT, MD, XLSX, ZIP</span>
        </div>
        <label className="flex items-center gap-2 text-small">
          <input type="checkbox" checked={demonstrateNow} onChange={(e) => setDemonstrateNow(e.target.checked)} className="accent-[var(--color-sunday)]" />
          Làm mẫu thử từng việc ngay sau khi đọc (máy phải để yên). Bỏ chọn để chỉ đọc, làm mẫu sau.
        </label>
        {(trainMemory?.not_tried ?? 0) > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" disabled={busy} onClick={() => void startTraining("verify", "")} className="rounded-sheet border border-ink px-4 py-2 font-medium disabled:opacity-40">
              Làm mẫu thử {trainMemory?.not_tried} việc chưa chạy thử
            </button>
            <span className="text-small text-lunar">Chạy khi máy rảnh: chạm chuột hay bàn phím là dừng.</span>
          </div>
        )}
        <form
          className="flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (link.trim()) void startTraining("link", link.trim()).then(() => setLink(""));
          }}
        >
          <label htmlFor="train-link" className="sr-only">Link</label>
          <input id="train-link" type="url" value={link} onChange={(e) => setLink(e.target.value)} placeholder="Dán link trang hướng dẫn (Guider đọc cả các trang cùng mục)" className="min-w-0 flex-1 rounded-sheet border border-edge bg-white px-3 py-2 placeholder:text-lunar" />
          <button type="submit" disabled={busy || !link.trim()} className="rounded-sheet border border-ink px-4 py-2 font-medium disabled:opacity-40">
            Đọc link
          </button>
        </form>
        <form
          className="flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void startTraining("research", topic.trim()).then(() => setTopic(""));
          }}
        >
          <label htmlFor="train-topic" className="sr-only">Chủ đề research</label>
          <input id="train-topic" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Chủ đề để tự research (để trống: Guider tự chọn việc còn thiếu)" className="min-w-0 flex-1 rounded-sheet border border-edge bg-white px-3 py-2 placeholder:text-lunar" />
          <button type="submit" disabled={busy || !train?.research} title={train?.research ? undefined : "Cần API key Gemini"} className="rounded-sheet border border-ink px-4 py-2 font-medium disabled:opacity-40">
            Tự research
          </button>
        </form>
        {!train?.research && <p className="text-small text-lunar">Tự research cần API key Gemini (tab Cài đặt).</p>}
      </div>

      {trainJob && (
        <div role="status" className="mt-6 rounded-b-sheet border border-edge border-t-[6px] border-t-glue bg-white px-4 py-3">
          <p className="font-medium">{p?.message ?? "Đang bắt đầu…"}</p>
          {p && p.total > 0 && (
            <div className="mt-2 h-2 bg-shell" aria-hidden="true">
              <div className="h-2 bg-sunday" style={{ width: `${Math.round((100 * p.done) / p.total)}%` }} />
            </div>
          )}
          {p?.phase === "demo" && <p className="mt-2 text-small text-sunday">Guider đang mở Office để làm mẫu thử. Đừng gõ phím hay bấm chuột.</p>}
          <button type="button" onClick={() => void cancelTraining()} className="mt-3 rounded-sheet border border-ink px-3 py-1 text-small font-medium">
            Dừng
          </button>
        </div>
      )}

      {trainLast && (
        <div aria-live="polite" className="mt-6 rounded-sheet border border-edge bg-white px-4 py-3 text-small">
          {trainLast.ok ? (
            <>
              <p className="font-medium">{trainLast.cancelled ? "Đã dừng" : "Học xong"} sau {trainLast.seconds} giây</p>
              <ul className="mt-1 grid gap-x-6 tabular-nums min-[700px]:grid-cols-2">
                <li>Đọc {trainLast.relevant}/{trainLast.chunks} đoạn có thao tác</li>
                <li>Tìm thấy {trainLast.tasks_found} việc</li>
                <li className="font-medium">{trainLast.added} việc mới đã làm mẫu đúng</li>
                <li>{trainLast.merged} gộp vào việc có sẵn</li>
                <li>{trainLast.pending} chờ xem</li>
                <li>{trainLast.rejected} bị loại (nút không có thật)</li>
                <li>{trainLast.notes_added} ghi chú mới</li>
              </ul>
            </>
          ) : (
            <p className="text-sunday">Chưa học được: {trainLast.error}</p>
          )}
          {trainLast.warning && <p className="mt-2 text-sunday">{trainLast.warning}</p>}
        </div>
      )}

      <h3 className="mt-8 font-medium">Hỏi kho kiến thức</h3>
      <form
        className="mt-2 flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void askKnowledge(question);
        }}
      >
        <label htmlFor="train-ask" className="sr-only">Câu hỏi</label>
        <input id="train-ask" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ví dụ: Khi nào nên dùng PivotTable?" className="min-w-0 flex-1 rounded-sheet border border-edge bg-white px-3 py-2 placeholder:text-lunar" />
        <button type="submit" disabled={asking || !question.trim()} className="rounded-sheet border border-ink px-4 py-2 font-medium disabled:opacity-40">
          {asking ? "Đang nghĩ…" : "Hỏi"}
        </button>
      </form>
      {trainAnswer && (
        <div className="mt-3 rounded-sheet border border-edge bg-white px-4 py-3">
          <p className="whitespace-pre-line">{trainAnswer.answer}</p>
          {trainAnswer.citations.length > 0 && (
            <ol className="mt-2 space-y-1 text-small text-lunar">
              {trainAnswer.citations.map((c) => (
                <li key={c.n}>
                  [{c.n}] {c.source}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      <h3 className="mt-8 font-medium">
        Bộ nhớ đã học
        <span className="block text-small font-normal text-lunar">
          {learned} việc, {trainMemory?.notes ?? 0} ghi chú
        </span>
      </h3>
      {apps.map(([app, a]) =>
        a.cards.length || a.pending.length ? (
          <div key={app} className="mt-3">
            <p className="text-small font-medium">{APP_NAME[app] ?? app}{a.extends ? `, thêm ${a.extends} cách hỏi cho việc có sẵn` : ""}</p>
            <ul>
              {a.cards.map((c) => (
                <li key={c.id} className="flex items-start gap-2 border-t border-edge py-2 text-small">
                  <span className="flex-1">
                    {c.title} <span className="text-lunar">· {c.source}</span>
                  </span>
                  <button type="button" aria-label={`Xoá ${c.title}`} onClick={() => void removeLearned("card", c.id, app)} className="px-1">
                    <Cross />
                  </button>
                </li>
              ))}
              {a.pending.map((c) => (
                <li key={c.id} className="flex items-start gap-2 border-t border-edge py-2 text-small">
                  <span className="flex-1">
                    <span className="text-sunday">Chờ xem:</span> {c.title} <span className="text-lunar">· {c.reason}</span>
                  </span>
                  <button type="button" aria-label={`Xoá ${c.title}`} onClick={() => void removeLearned("card", c.id, app)} className="px-1">
                    <Cross />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null,
      )}

      {trainMemory && trainMemory.sources.length > 0 && (
        <>
          <h3 className="mt-8 font-medium">Nguồn đã học</h3>
          <ul className="mt-2">
            {trainMemory.sources.map((s) => (
              <SourceRow key={`${s.date}-${s.name}`} s={s} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
