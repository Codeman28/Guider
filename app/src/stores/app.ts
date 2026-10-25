import { create } from "zustand";

import { RpcClient, RpcError } from "../rpc/client";
import type { CloudCheck, CreateResult, Progress, Settings, SystemCheck, Tutorial, TutorialMeta } from "../rpc/types";

export interface DoneStep {
  n: number;
  intent?: string;
  label?: string;
  seconds?: number;
}

export interface Demo {
  sid: string | null;
  question: string;
  startedAt: number;
  phase: "planning" | "demonstrating" | "finishing";
  current: { n: number; total: number; intent?: string; label?: string } | null;
  done: DoneStep[];
  recovered: boolean;
}

export type ChatEntry =
  | { kind: "question"; text: string }
  | { kind: "answer"; text: string }
  | { kind: "result"; tutorialId: string; title?: string; status: string; steps: number; seconds: number };

export type ViewMode = "article" | "steps";

const CONSENT_KEY = "guider.consent.v1";

function readConsent(): boolean {
  try {
    return localStorage.getItem(CONSENT_KEY) === "yes";
  } catch {
    return false;
  }
}

function writeConsent() {
  try {
    localStorage.setItem(CONSENT_KEY, "yes");
  } catch {
    /* private mode: consent is asked again next launch */
  }
}

interface State {
  client: RpcClient | null;
  consented: boolean;
  check: SystemCheck | null;
  checking: boolean;
  checkError: string | null;
  chat: ChatEntry[];
  demo: Demo | null;
  library: TutorialMeta[];
  libraryLoaded: boolean;
  tabs: { id: string; title: string }[];
  active: string | null;
  tutorials: Record<string, Tutorial>;
  mode: ViewMode;
  stepIndex: Record<string, number>;
  notice: string | null;
  sourceFile: string | null; // user-file mode (ADR-0003): Guider demonstrates on a private copy
  rewriting: Record<string, boolean>; // tutorial ids whose text the background Writer is still improving
  settings: Settings | null;
  cloud: CloudCheck | null;
  savingCloud: boolean;

  init(client: RpcClient): void;
  runCheck(): Promise<void>;
  agree(): void;
  ask(question: string): Promise<void>;
  cancel(): Promise<void>;
  open(id: string): Promise<void>;
  close(id: string): void;
  setActive(id: string | null): void;
  setMode(m: ViewMode): void;
  setStep(id: string, i: number): void;
  refreshLibrary(): Promise<void>;
  exportTutorial(id: string, format: "md" | "html"): Promise<string | null>;
  onProgress(p: Progress): void;
  onDone(r: CreateResult): void;
  onUpdated(id: string): Promise<void>;
  pickFile(): Promise<void>;
  clearFile(): void;
  loadSettings(): Promise<void>;
  useProvider(p: "ollama" | "gemini"): Promise<void>;
  saveGeminiKey(key: string): Promise<void>;
}

const FILE_TYPES = ["xlsx", "xlsm", "xls", "csv", "docx", "docm", "doc", "pptx", "pptm", "ppt"];

export const useApp = create<State>((set, get) => ({
  client: null,
  consented: readConsent(),
  check: null,
  checking: false,
  checkError: null,
  chat: [],
  demo: null,
  library: [],
  libraryLoaded: false,
  tabs: [],
  active: null,
  tutorials: {},
  mode: "article",
  stepIndex: {},
  notice: null,
  sourceFile: null,
  rewriting: {},
  settings: null,
  cloud: null,
  savingCloud: false,

  init(client) {
    set({ client });
    client.on("tutorial.progress", (p: Progress) => get().onProgress(p));
    client.on("tutorial.done", (r: CreateResult) => get().onDone(r));
    client.on("tutorial.updated", (u: { tutorial_id: string }) => void get().onUpdated(u.tutorial_id));
    void get().refreshLibrary();
    void get().loadSettings();
  },

  async runCheck() {
    const c = get().client;
    if (!c) return;
    set({ checking: true, checkError: null });
    try {
      set({ check: await c.call<SystemCheck>("system.check", { refresh: true }) });
    } catch (e) {
      set({ checkError: e instanceof Error ? e.message : String(e) });
    } finally {
      set({ checking: false });
    }
  },

  agree() {
    writeConsent();
    set({ consented: true });
  },

  async ask(question) {
    const q = question.trim();
    const c = get().client;
    if (!q || !c || get().demo) return;
    set((s) => ({
      chat: [...s.chat, { kind: "question", text: q }],
      demo: { sid: null, question: q, startedAt: Date.now(), phase: "planning", current: null, done: [], recovered: false },
    }));
    try {
      const file = get().sourceFile;
      const { session_id } = await c.call<{ session_id: string }>("tutorial.create", file ? { query: q, source_file: file } : { query: q });
      set((s) => (s.demo ? { demo: { ...s.demo, sid: session_id } } : {}));
    } catch (e) {
      const busy = e instanceof RpcError && e.code === -32001;
      set((s) => ({
        demo: null,
        chat: [...s.chat, { kind: "answer", text: busy ? "Guider đang làm mẫu một câu hỏi khác. Chờ xong rồi hỏi tiếp nhé." : `Không gửi được câu hỏi: ${e instanceof Error ? e.message : e}` }],
      }));
    }
  },

  async cancel() {
    const d = get().demo;
    if (d?.sid && get().client) await get().client!.call("tutorial.cancel", { session_id: d.sid });
  },

  onProgress(p) {
    set((s) => {
      const d = s.demo;
      if (!d || (d.sid && p.session_id !== d.sid)) return {};
      const next: Demo = { ...d, sid: d.sid ?? p.session_id };
      if (p.state === "RECOVER") next.recovered = true;
      if (["SETUP", "GROUND", "CAPTURE", "ACT", "VERIFY"].includes(p.state)) next.phase = "demonstrating";
      if (["TEARDOWN", "WRITE", "DONE"].includes(p.state)) next.phase = "finishing";
      if (p.step_i && (p.state === "ACT" || p.state === "GROUND")) {
        const total = Math.max(p.n_steps ?? 0, p.step_i);
        const same = next.current?.n === p.step_i;
        next.current = { n: p.step_i, total, intent: p.intent ?? (same ? next.current?.intent : undefined), label: p.label ?? (same ? next.current?.label : undefined) };
      }
      if (p.state === "STEP_DONE" && p.step_i) {
        next.done = [...next.done.filter((x) => x.n !== p.step_i), { n: p.step_i, intent: p.intent, label: p.label, seconds: p.seconds }];
        // after the last planned step there is no next sheet: show "finishing" instead of "4 / 4"
        next.current = p.step_i < (p.n_steps ?? 0) ? { n: p.step_i + 1, total: p.n_steps! } : null;
      }
      return { demo: next };
    });
  },

  onDone(r) {
    const d = get().demo;
    if (d?.sid && r.session_id !== d.sid) return;
    const seconds = Math.round((Date.now() - (d?.startedAt ?? Date.now())) / 1000);
    if (r.kind === "tutorial" && r.tutorial_id) {
      const pending = r.writer_source === "llm_pending";
      set((s) => ({
        demo: null,
        rewriting: pending ? { ...s.rewriting, [r.tutorial_id!]: true } : s.rewriting,
        chat: [...s.chat, { kind: "result", tutorialId: r.tutorial_id!, status: r.status ?? "ok", steps: d?.done.length ?? 0, seconds }],
      }));
      void get().open(r.tutorial_id);
      void get().refreshLibrary();
    } else {
      set((s) => ({ demo: null, chat: [...s.chat, { kind: "answer", text: r.answer ?? "Guider chưa trả lời được câu này." }] }));
    }
  },

  async onUpdated(id) {
    // the background Writer replaced the template text: reload the tutorial if it is loaded
    const c = get().client;
    set((s) => {
      const { [id]: _, ...rest } = s.rewriting;
      return { rewriting: rest };
    });
    if (!c || !get().tutorials[id]) return;
    try {
      const t = await c.call<Tutorial>("tutorial.get", { tutorial_id: id });
      set((s) => ({
        tutorials: { ...s.tutorials, [id]: t },
        tabs: s.tabs.map((x) => (x.id === id ? { ...x, title: t.title } : x)),
      }));
    } catch {
      /* keep the template text that is already on screen */
    }
  },

  async pickFile() {
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const picked = await open({
        multiple: false,
        directory: false,
        title: "Chọn file để Guider làm mẫu (Guider dùng bản sao, không sửa file này)",
        filters: [{ name: "Excel, Word, PowerPoint", extensions: FILE_TYPES }],
      });
      if (typeof picked === "string") set({ sourceFile: picked });
    } catch (e) {
      set({ notice: `Không mở được hộp chọn file: ${e instanceof Error ? e.message : e}` });
    }
  },

  clearFile: () => set({ sourceFile: null }),

  async loadSettings() {
    const c = get().client;
    if (!c) return;
    try {
      set({ settings: await c.call<Settings>("settings.get") });
    } catch {
      /* settings are optional: the local model stays the default */
    }
  },

  async useProvider(p) {
    const c = get().client;
    if (!c) return;
    try {
      set({ settings: await c.call<Settings>("settings.set", { provider: p }), cloud: null });
    } catch (e) {
      set({ notice: `Không đổi được model: ${e instanceof Error ? e.message : e}` });
    }
  },

  async saveGeminiKey(key) {
    const c = get().client;
    if (!c) return;
    set({ savingCloud: true, cloud: null });
    try {
      await c.call("settings.set_api_key", { provider: "gemini", key: key.trim() || null });
      const cloud = key.trim() ? await c.call<CloudCheck>("settings.check_cloud", { provider: "gemini" }) : null;
      set({ cloud, settings: await c.call<Settings>("settings.get") });
      if (cloud?.ok) await get().useProvider("gemini");
    } catch (e) {
      set({ cloud: { ok: false, error: e instanceof Error ? e.message : String(e) } });
    } finally {
      set({ savingCloud: false });
    }
  },

  async open(id) {
    const c = get().client;
    if (!c) return;
    let t = get().tutorials[id];
    if (!t) {
      try {
        t = await c.call<Tutorial>("tutorial.get", { tutorial_id: id });
      } catch (e) {
        set({ notice: `Không mở được hướng dẫn: ${e instanceof Error ? e.message : e}` });
        return;
      }
      set((s) => ({ tutorials: { ...s.tutorials, [id]: t! } }));
    }
    set((s) => ({
      tabs: s.tabs.some((x) => x.id === id) ? s.tabs : [...s.tabs, { id, title: t!.title }],
      active: id,
      chat: s.chat.map((e) => (e.kind === "result" && e.tutorialId === id ? { ...e, title: t!.title } : e)),
    }));
  },

  close(id) {
    set((s) => {
      const tabs = s.tabs.filter((x) => x.id !== id);
      return { tabs, active: s.active === id ? (tabs.at(-1)?.id ?? null) : s.active };
    });
  },

  setActive: (id) => set({ active: id }),
  setMode: (m) => set({ mode: m }),
  setStep: (id, i) => set((s) => ({ stepIndex: { ...s.stepIndex, [id]: i } })),

  async refreshLibrary() {
    const c = get().client;
    if (!c) return;
    try {
      set({ library: await c.call<TutorialMeta[]>("tutorial.list"), libraryLoaded: true });
    } catch {
      /* the library is a convenience; the chat still works */
    }
  },

  async exportTutorial(id, format) {
    const c = get().client;
    if (!c) return null;
    try {
      const { path } = await c.call<{ path: string }>("tutorial.export", { tutorial_id: id, format });
      set({ notice: `Đã xuất: ${path}` });
      return path;
    } catch (e) {
      set({ notice: `Không xuất được: ${e instanceof Error ? e.message : e}` });
      return null;
    }
  },
}));
