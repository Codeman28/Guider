import { useCallback, useEffect, useState } from "react";

import type { PracticeList } from "../rpc/types";

import { Check, Cross } from "../lib/icons";
import { useApp } from "../stores/app";

const AI_STUDIO = "https://aistudio.google.com/apikey";

function Choice({ checked, onSelect, title, detail }: { checked: boolean; onSelect: () => void; title: string; detail: string }) {
  return (
    <label className={`grid cursor-pointer grid-cols-[24px_1fr] gap-2 rounded-sheet border bg-white px-3.5 py-3 ${checked ? "border-ink" : "border-edge"}`}>
      <input type="radio" name="provider" checked={checked} onChange={onSelect} className="mt-1.5 accent-[var(--color-sunday)]" />
      <span>
        <span className="block font-medium">{title}</span>
        <span className="block text-small text-lunar">{detail}</span>
      </span>
    </label>
  );
}

const APP_NAME = { excel: "Excel", word: "Word", powerpoint: "PowerPoint" } as const;

/** Goals the agent has not reached yet (ADR-0008): Guider tries them again later, with what it learned. */
function Practice() {
  const { client } = useApp();
  const [list, setList] = useState<PracticeList | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!client) return;
    try {
      setList(await client.call<PracticeList>("practice.list"));
    } catch {
      /* older engine: no practice queue */
    }
  }, [client]);

  useEffect(() => {
    void load();
    if (!client) return;
    const offProgress = client.on("practice.progress", (p: { message?: string }) => setRunning(p.message ?? "Đang luyện…"));
    const offDone = client.on("practice.done", () => {
      setRunning(null);
      void load();
    });
    return () => {
      offProgress();
      offDone();
    };
  }, [client, load]);

  if (!list) return null;
  const open = list.goals.filter((g) => !g.solved);
  const solved = list.goals.filter((g) => g.solved);

  return (
    <div className="mt-8 border-t border-edge pt-6">
      <h3 className="font-semibold">Guider tự học</h3>
      <p className="mt-1 max-w-[600px] text-small text-lunar">
        Việc nào Guider làm chưa được sau vài lượt sẽ được ghi vào đây cùng bài học rút ra. Guider luyện lại các việc này,
        mỗi lần một việc, và làm được thì lưu thành cách làm cho lần sau.
      </p>
      <label className="mt-3 flex max-w-[600px] items-start gap-3">
        <input
          type="checkbox"
          className="mt-1 h-4 w-4"
          checked={list.auto}
          onChange={async (e) => {
            if (!client) return;
            await client.call("settings.set", { auto_practice: e.target.checked });
            void load();
          }}
        />
        <span>
          <span className="font-medium">Tự luyện khi máy rảnh</span>
          <span className="block text-small text-lunar">
            Sau 10 phút không ai dùng chuột hay bàn phím, Guider mở file mẫu và luyện. Bạn chạm vào máy là Guider dừng ngay.
          </span>
        </span>
      </label>
      {open.length === 0 ? (
        <p className="mt-3 text-small">Chưa có việc nào cần luyện.</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {open.map((g) => (
            <li key={`${g.app}:${g.goal}`} className="rounded-sheet border border-edge bg-white px-3.5 py-2.5">
              <span className="block font-medium">{g.goal}</span>
              <span className="block text-small text-lunar">
                {APP_NAME[g.app]} · đã luyện {g.tries} lần{g.why ? ` · lần gần nhất: ${g.why}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
      {solved.length > 0 && <p className="mt-3 text-small text-lunar">Đã tự học được: {solved.map((g) => g.goal).join("; ")}</p>}
      <div className="mt-3 flex items-center gap-3">
        <button
          type="button"
          disabled={!!running || list.pending === 0}
          onClick={async () => {
            if (!client) return;
            setError(null);
            try {
              const r = await client.call<{ started: boolean; reason?: string }>("practice.run");
              if (r.started) setRunning("Đang luyện…");
              else setError(r.reason ?? null);
            } catch (e) {
              setError(e instanceof Error ? e.message : String(e));
            }
          }}
          className="rounded-sheet bg-ink px-4 py-2 font-medium text-paper disabled:opacity-40"
        >
          {running ? "Đang luyện…" : "Luyện ngay một việc"}
        </button>
        {running && <span aria-live="polite" className="text-small text-lunar">{running}</span>}
        {error && <span className="text-small text-sunday">{error}</span>}
      </div>
    </div>
  );
}

export function Settings() {
  const { settings, cloud, savingCloud, useProvider, saveGeminiKey, setVisionCloud } = useApp();
  const [key, setKey] = useState("");
  const provider = settings?.provider ?? "ollama";
  const hasKey = settings?.has_key?.gemini ?? false;

  return (
    <section aria-labelledby="settings-title" className="mx-auto max-w-[680px] px-8 py-8">
      <h2 id="settings-title" className="text-title font-bold leading-tight">
        Cài đặt
      </h2>

      <h3 className="mt-6 font-medium">Model viết kế hoạch và lời văn</h3>
      <div className="mt-3 space-y-2" role="radiogroup" aria-label="Model">
        <Choice
          checked={provider === "ollama"}
          onSelect={() => void useProvider("ollama")}
          title="Model trên máy (Ollama)"
          detail="Không gửi gì lên mạng. Chậm hơn trên máy không có card đồ hoạ rời."
        />
        <Choice
          checked={provider === "gemini"}
          onSelect={() => hasKey && void useProvider("gemini")}
          title="Gemini miễn phí (Google)"
          detail={hasKey ? "Nhanh hơn nhiều. Lỗi mạng hoặc hết lượt thì Guider tự dùng model trên máy." : "Cần API key của bạn, nhập ở dưới."}
        />
      </div>

      <div className="mt-6 rounded-b-sheet border border-edge border-t-[6px] border-t-glue bg-white px-4 py-4">
        <label htmlFor="gemini-key" className="font-medium">
          API key Gemini
        </label>
        <p className="mt-1 text-small text-lunar">
          Tạo miễn phí tại <span className="font-medium text-ink">{AI_STUDIO}</span> rồi dán vào đây. Key được mã hoá theo tài khoản Windows của bạn và chỉ nằm trên máy này.
        </p>
        <p className="mt-2 text-small">
          Lưu ý: ở gói miễn phí, Google có thể dùng dữ liệu gửi lên để cải thiện sản phẩm. Guider chỉ gửi câu hỏi và tên các nút; không gửi nội dung file, và ảnh chụp vấn đề được gửi khi mục "Đọc ảnh bằng Gemini" bên dưới đang bật.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <input
            id="gemini-key"
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder={hasKey ? "Đã lưu một key; dán key mới để thay" : "Dán API key"}
            className="min-w-0 flex-1 rounded-sheet border border-edge bg-white px-3 py-2 placeholder:text-lunar"
          />
          <button
            type="button"
            disabled={savingCloud || !key.trim()}
            onClick={() => {
              void saveGeminiKey(key);
              setKey("");
            }}
            className="rounded-sheet bg-ink px-4 py-2 font-medium text-paper disabled:opacity-40"
          >
            {savingCloud ? "Đang kiểm tra…" : "Lưu và kiểm tra"}
          </button>
          {hasKey && (
            <button type="button" disabled={savingCloud} onClick={() => void saveGeminiKey("").then(() => useProvider("ollama"))} className="rounded-sheet border border-ink px-4 py-2 font-medium disabled:opacity-40">
              Xoá key
            </button>
          )}
        </div>
        {cloud && (
          <p aria-live="polite" className="mt-3 flex items-start gap-2 text-small">
            {cloud.ok ? <Check label="đạt" /> : <Cross label="chưa đạt" className="text-sunday" />}
            <span>{cloud.ok ? `Gemini trả lời sau ${cloud.seconds} giây (${cloud.model}). Đã chuyển sang Gemini.` : `Chưa dùng được Gemini: ${cloud.error}`}</span>
          </p>
        )}
      </div>

      <div className="mt-8 border-t border-edge pt-6">
        <h3 className="font-semibold">Đọc ảnh chụp vấn đề</h3>
        <p className="mt-1 max-w-[600px] text-small text-lunar">
          Khi đã có API key, Guider gửi ảnh lên Gemini để đọc (vài giây). Tắt mục dưới thì Guider đọc ảnh ngay trên máy bằng model gemma3:4b: ảnh không rời máy, nhưng mất khoảng 1–2 phút mỗi ảnh trên máy không có card đồ họa.
        </p>
        <label className="mt-3 flex max-w-[600px] items-start gap-3">
          <input
            type="checkbox"
            className="mt-1 h-4 w-4"
            disabled={!hasKey}
            checked={settings?.vision_cloud !== false && hasKey}
            onChange={(e) => void setVisionCloud(e.target.checked)}
          />
          <span>
            <span className="font-medium">Đọc ảnh bằng Gemini (nhanh, vài giây)</span>
            <span className="block text-small text-sunday">
              Ảnh bạn gửi sẽ được tải lên Google. Gói miễn phí cho phép Google dùng dữ liệu gửi lên. Đừng bật nếu ảnh có thông tin riêng tư.
            </span>
            {!hasKey && <span className="block text-small text-lunar">Cần lưu API key Gemini ở trên trước.</span>}
          </span>
        </label>
      </div>

      <Practice />
    </section>
  );
}
