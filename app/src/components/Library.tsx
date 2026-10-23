import { useApp } from "../stores/app";

const STATUS: Record<string, string> = { ok: "Đầy đủ", partial: "Một phần", failed: "Chưa làm mẫu được", cancelled: "Đã dừng" };

/** Tutorial history as whole-cell mini calendar sheets: the day it was made, big. */
export function Library() {
  const { library, open } = useApp();

  if (library.length === 0) {
    return (
      <div className="mx-auto max-w-[560px] px-6 py-16">
        <p className="font-num text-sm tracking-[0.12em] text-lunar">THƯ VIỆN</p>
        <h1 className="mt-1 text-[28px] font-bold leading-tight">Chưa có hướng dẫn nào</h1>
        <p className="mt-3 text-[17px]">
          Mỗi câu bạn hỏi sẽ thành một hướng dẫn chụp trên chính Excel của bạn và được giữ ở đây, kể cả khi tắt máy.
        </p>
      </div>
    );
  }

  return (
    <section aria-label="Thư viện hướng dẫn" className="px-6 py-6">
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-3">
        {library.map((m) => {
          const d = new Date(m.created * 1000);
          return (
            <li key={m.tutorial_id}>
              <button type="button" onClick={() => void open(m.tutorial_id)} className="h-full w-full rounded-sheet border border-edge border-t-[6px] border-t-glue bg-white p-3 text-left hover:border-ink">
                <span className="block font-num text-sm tracking-[0.12em] text-lunar">THÁNG {d.getMonth() + 1}</span>
                <span className={`block font-num text-[48px] font-bold leading-none ${d.getDay() === 0 ? "text-sunday" : ""}`}>{d.getDate()}</span>
                <span className="mt-2 block font-medium">{m.title}</span>
                <span className={`mt-1 block text-xs ${m.status === "ok" ? "text-lunar" : "text-sunday"}`}>{STATUS[m.status] ?? m.status}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
