import { useEffect, useRef, useState } from "react";

import { Check } from "../lib/icons";
import { Rich, actionText, seconds } from "../lib/rich";
import type { Demo } from "../stores/app";

/** The live demonstration as a tear-off calendar: the current step is the top sheet with a
 *  monumental numeral; when it verifies, the sheet tears away and becomes a stub below. */
export function StepStack({ demo }: { demo: Demo }) {
  const [tearing, setTearing] = useState<number | null>(null);
  const lastDone = useRef(0);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const n = demo.done.length ? Math.max(...demo.done.map((d) => d.n)) : 0;
    if (n > lastDone.current) {
      lastDone.current = n;
      setTearing(n);
      const t = setTimeout(() => setTearing(null), 420);
      return () => clearTimeout(t);
    }
  }, [demo.done]);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const elapsed = Math.round((now - demo.startedAt) / 1000);
  const cur = demo.current;
  const total = cur?.total ?? 0;
  const tornDone = demo.done.find((d) => d.n === tearing);

  return (
    <section aria-label="Tiến độ làm mẫu" className="mx-5">
      <div className="relative">
        {tornDone && (
          <Sheet n={tornDone.n} total={Math.max(total, tornDone.n)} text={actionText(tornDone.intent, tornDone.label)} sub={`xong sau ${seconds(tornDone.seconds)}`} className="sheet-tearing absolute inset-x-0 top-0 z-10" />
        )}
        {demo.phase === "planning" ? (
          <Sheet n={null} total={0} text="Guider đang đọc câu hỏi và lập kế hoạch các bước…" sub={`${elapsed} giây — model chạy trên máy nên có thể mất vài chục giây`} />
        ) : demo.phase === "finishing" || !cur ? (
          <Sheet n={null} total={0} text="Đang đóng file mẫu và viết hướng dẫn…" sub={`${elapsed} giây`} />
        ) : (
          <Sheet n={cur.n} total={total} text={actionText(cur.intent, cur.label)} sub={`${elapsed} giây từ lúc bắt đầu`} />
        )}
        <div aria-hidden className="mx-1 h-2.5 rounded-b-sheet border border-t-0 border-edge bg-white" />
      </div>

      <ol aria-live="polite" className="mt-3 space-y-1.5 text-small">
        {[...demo.done].sort((a, b) => a.n - b.n).map((d) => (
          <li key={d.n} className="grid grid-cols-[20px_1fr_auto] items-baseline gap-2">
            <Check className="translate-y-0.5" />
            <span>
              Bước {d.n}: <Rich text={actionText(d.intent, d.label)} />
            </span>
            <span className="font-num tabular-nums tracking-wide text-lunar">{seconds(d.seconds)}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Sheet({ n, total, text, sub, className = "" }: { n: number | null; total: number; text: string; sub: string; className?: string }) {
  return (
    <div className={`rounded-b-sheet border border-edge border-t-[6px] border-t-glue bg-white px-4 pb-3 pt-3 ${className}`}>
      {n !== null && (
        <>
          <p className="text-small text-lunar">Bước</p>
          <p className="font-num text-[92px] font-bold leading-none">{n}</p>
          {total > 0 && <p className="mt-2 text-small text-lunar">trên {total}</p>}
        </>
      )}
      <p className="mt-1.5 font-medium">
        <Rich text={text} />
      </p>
      <p className="mt-0.5 text-small tabular-nums text-lunar">{sub}</p>
    </div>
  );
}
