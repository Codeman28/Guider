import { useEffect, useMemo, useState } from "react";

import { Cross } from "../lib/icons";
import { useApp } from "../stores/app";

const STATUS: Record<string, string> = { ok: "Đầy đủ", partial: "Một phần", failed: "Chưa làm mẫu được", cancelled: "Đã dừng" };

/** Lowercase, no Vietnamese marks (đ → d): "Biểu đồ" matches "bieu do". Same idea as the engine's fold(). */
function fold(s: string): string {
  return s.toLowerCase().replace(/đ/g, "d").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/\s+/g, " ").trim();
}

function mb(bytes: number): string {
  return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** Tutorial history as whole-cell mini calendar sheets: the day it was made, big. */
export function Library() {
  const { library, libraryLoaded, open, deleteTutorials } = useApp();
  const [query, setQuery] = useState("");
  const [confirm, setConfirm] = useState<string | null>(null); // tutorial id, or "all" for the shown ones

  // a pending "Xoá thật?" quietly goes back after a few seconds
  useEffect(() => {
    if (!confirm) return;
    const t = setTimeout(() => setConfirm(null), 4000);
    return () => clearTimeout(t);
  }, [confirm]);

  const shown = useMemo(() => {
    const q = fold(query);
    return q ? library.filter((m) => q.split(" ").every((w) => fold(m.title).includes(w))) : library;
  }, [library, query]);
  const total = library.reduce((n, m) => n + (m.bytes ?? 0), 0);
  const shownBytes = shown.reduce((n, m) => n + (m.bytes ?? 0), 0);

  // never claim "no tutorials yet" before the engine has answered
  if (!libraryLoaded) return <p className="px-6 py-6 text-small text-lunar" role="status">Đang mở thư viện…</p>;

  if (library.length === 0) {
    return (
      <div className="mx-auto max-w-[560px] px-6 py-16">
        <h1 className="text-title font-bold leading-tight">Chưa có hướng dẫn nào</h1>
        <p className="mt-3">
          Mỗi câu bạn hỏi sẽ thành một hướng dẫn chụp trên chính Office của bạn và được giữ ở đây, kể cả khi tắt máy.
        </p>
      </div>
    );
  }

  return (
    <section aria-label="Thư viện hướng dẫn" className="px-6 py-6">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <label htmlFor="lib-search" className="sr-only">Tìm hướng dẫn</label>
        <input
          id="lib-search"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Tìm hướng dẫn… (gõ có dấu hay không đều được)"
          className="min-w-0 flex-1 rounded-sheet border border-edge bg-white px-3 py-2 placeholder:text-lunar"
        />
        <span className="text-small tabular-nums text-lunar">
          {query ? `${shown.length}/${library.length} bài` : `${library.length} bài`}, {mb(total)}
        </span>
        {query && shown.length > 0 && (
          <button
            type="button"
            onClick={() => (confirm === "all" ? (void deleteTutorials(shown.map((m) => m.tutorial_id)), setConfirm(null)) : setConfirm("all"))}
            className={`rounded-sheet border px-3 py-1.5 text-small font-medium ${confirm === "all" ? "border-sunday bg-sunday text-paper" : "border-ink"}`}
          >
            {confirm === "all" ? `Xoá thật ${shown.length} bài (${mb(shownBytes)})?` : `Xoá ${shown.length} bài đang hiện`}
          </button>
        )}
      </div>

      {shown.length === 0 ? (
        <p className="text-lunar">Không có hướng dẫn nào khớp “{query}”.</p>
      ) : (
        <ul className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-3">
          {shown.map((m) => {
            const d = new Date(m.created * 1000);
            const asking = confirm === m.tutorial_id;
            return (
              <li key={m.tutorial_id} className="relative">
                <button type="button" onClick={() => void open(m.tutorial_id)} className="flex h-full w-full flex-col items-start justify-start rounded-b-sheet border border-edge border-t-[6px] border-t-glue bg-white p-3 pr-9 text-left hover:border-ink">
                  <span className="block text-small text-lunar">tháng {d.getMonth() + 1}</span>
                  <span className={`block font-num text-[48px] font-bold leading-none ${d.getDay() === 0 ? "text-sunday" : ""}`}>{d.getDate()}</span>
                  <span className="mt-2 block font-medium">{m.title}</span>
                  <span className={`mt-1 block text-small ${m.status === "ok" ? "text-lunar" : "text-sunday"}`}>
                    {STATUS[m.status] ?? m.status}
                    {m.bytes ? <span className="block text-lunar">{mb(m.bytes)}</span> : null}
                  </span>
                </button>
                <button
                  type="button"
                  aria-label={asking ? `Xác nhận xoá ${m.title}` : `Xoá ${m.title}`}
                  onClick={() => (asking ? (void deleteTutorials([m.tutorial_id]), setConfirm(null)) : setConfirm(m.tutorial_id))}
                  className={`absolute right-1.5 top-2.5 rounded-sheet px-1.5 py-1 text-small ${asking ? "bg-sunday font-medium text-paper" : "text-lunar hover:text-ink"}`}
                >
                  {asking ? "Xoá thật?" : <Cross />}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
