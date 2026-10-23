import { convertFileSrc } from "@tauri-apps/api/core";
import { useEffect, useState } from "react";

import { ArrowLeft, ArrowRight, Check, Cross } from "../lib/icons";
import { Rich, actionText, stripStepPrefix } from "../lib/rich";
import { inTauri } from "../rpc/client";
import type { Tutorial, TutorialStep } from "../rpc/types";
import { useApp } from "../stores/app";

/** Screenshots are physical-pixel captures; one shared factor keeps every step at the same scale on
 *  the same baseline (direction contract raise), capped by the column width. */
const SHOT_SCALE = 0.62;

const NOT_DEMONSTRATED = "Bước này Guider chưa làm mẫu được trên máy bạn.";

/** PRODUCT.md: an undemonstrated step always says so in plain words, whoever wrote the body. */
function stepBody(s: TutorialStep): string {
  return s.demonstrated || s.body.startsWith(NOT_DEMONSTRATED.slice(0, -1)) ? s.body : `${NOT_DEMONSTRATED} ${s.body}`;
}

/** Local tutorial images go through Tauri's asset protocol (scope: %LOCALAPPDATA%\Kem\tutorials). */
function src(dir: string, file: string): string {
  return inTauri() ? convertFileSrc(`${dir}\\${file}`) : "";
}

function Shot({ dir, file, alt }: { dir: string; file: string; alt: string }) {
  const [w, setW] = useState<number | null>(null);
  const url = src(dir, file);
  if (!url) return <div className="aspect-[16/7] w-full max-w-[860px] rounded-sheet border border-edge bg-white" aria-label={alt} />;
  return (
    <img
      src={url}
      alt={alt}
      onLoad={(e) => setW(e.currentTarget.naturalWidth)}
      style={w ? { width: `${Math.round(w * SHOT_SCALE)}px` } : undefined}
      className="block max-w-full rounded-sheet border border-edge bg-white"
    />
  );
}

function Step({ t, s, n, big }: { t: Tutorial; s: TutorialStep; n: number; big: boolean }) {
  return (
    <section aria-labelledby={`h-${t.tutorial_id}-${n}`} className="grid grid-cols-[96px_minmax(0,1fr)] gap-6 border-t border-edge py-6 first:border-t-0 min-[1100px]:grid-cols-[150px_minmax(0,1fr)]">
      <div aria-hidden>
        <p className="font-num text-small tracking-[0.12em] text-lunar">BƯỚC</p>
        <p className={`font-num font-bold leading-none ${big ? "text-[96px] min-[1100px]:text-[140px]" : "text-[72px] min-[1100px]:text-[96px]"} ${s.demonstrated ? "" : "text-sunday"}`}>{n}</p>
        <p className="mt-2 font-num text-small tracking-[0.12em] text-lunar">TRÊN {t.steps.length}</p>
      </div>
      <div className="min-w-0">
        <h2 id={`h-${t.tutorial_id}-${n}`} className="font-semibold">
          <span className="sr-only">Bước {n}: </span>
          <Rich text={stripStepPrefix(s.heading)} />
        </h2>
        {s.image && (
          <div className="mt-3">
            <Shot dir={t.dir} file={s.image} alt={`Ảnh chụp bước ${n} trên máy bạn`} />
          </div>
        )}
        <p className="mt-3 max-w-[680px]">
          <Rich text={stepBody(s)} />
        </p>
        {s.tip && <p className="mt-2 text-small text-lunar"><Rich text={s.tip} /></p>}
        {s.result_image && (
          <div className="mt-4">
            <p className="mb-2 text-small text-lunar">Kết quả sau bước này</p>
            <Shot dir={t.dir} file={s.result_image} alt={`Kết quả sau bước ${n}`} />
          </div>
        )}
      </div>
    </section>
  );
}

export function TutorialView({ t }: { t: Tutorial }) {
  const { mode, setMode, stepIndex, setStep, exportTutorial } = useApp();
  const [traceOpen, setTraceOpen] = useState(false);
  const i = Math.min(stepIndex[t.tutorial_id] ?? 0, t.steps.length - 1);

  useEffect(() => {
    if (mode !== "steps") return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "TEXTAREA") return;
      if (e.key === "ArrowRight") setStep(t.tutorial_id, Math.min(i + 1, t.steps.length - 1));
      if (e.key === "ArrowLeft") setStep(t.tutorial_id, Math.max(i - 1, 0));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mode, i, t, setStep]);

  return (
    <article className="mx-auto max-w-[1180px] px-6 py-6 min-[1100px]:px-12">
      <header className="border-b border-edge pb-4">
        <h1 className="text-title font-bold leading-tight">{t.title}</h1>
        <p className="mt-1 text-small text-lunar">{t.env_label}</p>
        <div className="no-print mt-4 flex flex-wrap items-center gap-2 text-small">
          <div role="group" aria-label="Cách đọc" className="flex overflow-hidden rounded-sheet border border-ink">
            {(["article", "steps"] as const).map((m) => (
              <button key={m} type="button" aria-pressed={mode === m} onClick={() => setMode(m)} className={`px-3 py-1.5 font-medium ${mode === m ? "bg-ink text-paper" : "bg-white"}`}>
                {m === "article" ? "Bài đầy đủ" : "Từng bước"}
              </button>
            ))}
          </div>
          <span className="mx-1 h-5 w-px bg-edge" aria-hidden />
          <button type="button" onClick={() => void exportTutorial(t.tutorial_id, "md")} className="rounded-sheet border border-edge bg-white px-3 py-1.5">Xuất Markdown</button>
          <button type="button" onClick={() => void exportTutorial(t.tutorial_id, "html")} className="rounded-sheet border border-edge bg-white px-3 py-1.5">Xuất HTML</button>
          <button type="button" onClick={() => window.print()} className="rounded-sheet border border-edge bg-white px-3 py-1.5">In / lưu PDF</button>
          <button type="button" aria-expanded={traceOpen} onClick={() => setTraceOpen((v) => !v)} className="rounded-sheet border border-edge bg-white px-3 py-1.5">
            Xem Guider đã làm gì
          </button>
        </div>
        {traceOpen && t.trace && (
          <div className="no-print mt-4 rounded-sheet border border-edge bg-white p-4 text-small">
            <p className="font-medium">Nhật ký làm mẫu · {t.trace.llm_calls ?? 0} lần gọi model trên máy</p>
            <ol className="mt-2 space-y-1">
              {t.trace.steps.map((s) => (
                <li key={s.id} className="grid grid-cols-[24px_1fr] items-baseline gap-2">
                  {s.verified ? <Check label="đã xác minh" className="translate-y-0.5" /> : <Cross label="không xác minh được" className="translate-y-0.5 text-sunday" />}
                  <span>
                    <Rich text={actionText(s.intent, s.element_name ?? undefined)} />
                    {s.attempts > 1 ? ` · thử ${s.attempts} lần` : ""}
                    {s.inserted_reason ? ` · thêm vì ${s.inserted_reason}` : ""}
                    {s.error ? <span className="text-sunday"> · {s.error}</span> : null}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        )}
      </header>

      <p className="mt-5 max-w-[680px]">{t.intro}</p>

      {mode === "article" ? (
        <div className="mt-2">
          {t.steps.map((s, k) => <Step key={s.id} t={t} s={s} n={k + 1} big={false} />)}
        </div>
      ) : (
        <div className="mt-2">
          <Step t={t} s={t.steps[i]} n={i + 1} big />
          <nav aria-label="Chuyển bước" className="no-print flex items-center gap-3 border-t border-edge pt-4">
            <button type="button" disabled={i === 0} onClick={() => setStep(t.tutorial_id, i - 1)} className="inline-flex items-center gap-2 rounded-sheet border border-ink px-4 py-2 font-medium disabled:opacity-40"><ArrowLeft /> Lùi</button>
            <span className="font-num tabular-nums tracking-wide text-lunar">{i + 1} / {t.steps.length}</span>
            <button type="button" disabled={i === t.steps.length - 1} onClick={() => setStep(t.tutorial_id, i + 1)} className="inline-flex items-center gap-2 rounded-sheet bg-ink px-4 py-2 font-medium text-paper disabled:opacity-40">Bước tiếp <ArrowRight /></button>
          </nav>
        </div>
      )}

      {(mode === "article" || i === t.steps.length - 1) && (
        <p className={`mt-6 max-w-[680px] border-t border-edge pt-4 ${t.status === "ok" ? "" : "text-sunday"}`}>{t.outro}</p>
      )}
    </article>
  );
}
