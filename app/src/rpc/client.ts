// JSON-RPC 2.0 client over the Tauri relay (one JSON object per line). Outside Tauri (plain `vite`,
// tests) a PreviewTransport answers with clearly labelled preview data so the UI can be developed.

export interface Transport {
  send(line: string): Promise<void>;
  onLine(cb: (line: string) => void): Promise<() => void>;
}

type Pending = { resolve: (v: unknown) => void; reject: (e: Error) => void };
type Handler = (params: any) => void;

export class RpcError extends Error {
  constructor(public code: number, message: string) {
    super(message);
  }
}

export class RpcClient {
  private nextId = 1;
  private pending = new Map<number, Pending>();
  private handlers = new Map<string, Set<Handler>>();
  private ready: Promise<() => void>;

  constructor(private transport: Transport) {
    this.ready = transport.onLine((line) => this.receive(line));
  }

  receive(line: string) {
    let msg: any;
    try {
      msg = JSON.parse(line);
    } catch {
      return; // not ours (stray output); the engine only writes JSON-RPC on stdout
    }
    if (msg && typeof msg.id === "number" && this.pending.has(msg.id)) {
      const p = this.pending.get(msg.id)!;
      this.pending.delete(msg.id);
      if (msg.error) p.reject(new RpcError(msg.error.code, msg.error.message));
      else p.resolve(msg.result);
    } else if (msg && typeof msg.method === "string") {
      this.handlers.get(msg.method)?.forEach((h) => h(msg.params));
    }
  }

  async call<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    await this.ready;
    const id = this.nextId++;
    const result = new Promise<T>((resolve, reject) =>
      this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject }),
    );
    try {
      await this.transport.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
    } catch (e) {
      this.pending.delete(id);
      throw new Error(String(e));
    }
    return result;
  }

  on(method: string, handler: Handler): () => void {
    if (!this.handlers.has(method)) this.handlers.set(method, new Set());
    this.handlers.get(method)!.add(handler);
    return () => this.handlers.get(method)!.delete(handler);
  }
}

export function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export class TauriTransport implements Transport {
  async send(line: string) {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("engine_send", { line });
  }
  async onLine(cb: (line: string) => void) {
    const { listen } = await import("@tauri-apps/api/event");
    return listen<string>("engine://line", (e) => cb(e.payload));
  }
}

/** Preview data for running the UI outside the desktop shell. Never shown inside the real app. */
export class PreviewTransport implements Transport {
  private cb: (line: string) => void = () => {};
  async onLine(cb: (line: string) => void) {
    this.cb = cb;
    return () => {};
  }
  private reply(id: number, result: unknown) {
    setTimeout(() => this.cb(JSON.stringify({ jsonrpc: "2.0", id, result })), 30);
  }
  private notify(method: string, params: unknown, ms: number) {
    setTimeout(() => this.cb(JSON.stringify({ jsonrpc: "2.0", method, params })), ms);
  }
  async send(line: string) {
    const { id, method } = JSON.parse(line);
    if (method === "system.check")
      return this.reply(id, {
        excel: { ok: true, version: "16.0", build: "preview", ui_lang: "en-US" },
        model: { ok: true, provider: "ollama", model: "preview", missing: [] },
      });
    if (method === "tutorial.list" || method === "settings.get")
      return this.reply(id, method === "settings.get" ? { provider: "ollama", has_key: { gemini: false } } : []);
    if (method === "tutorial.create") {
      const sid = "preview";
      this.reply(id, { session_id: sid });
      const steps = [["select_ribbon_tab", "Insert", 4.2], ["invoke", "PivotTable", 6.8], ["invoke", "OK", 5.1]] as const;
      let t = 600;
      this.notify("tutorial.progress", { session_id: sid, state: "SETUP", message: "Xem thử" }, (t += 300));
      steps.forEach(([intent, label, s], i) => {
        this.notify("tutorial.progress", { session_id: sid, state: "ACT", step_i: i + 1, n_steps: 3, intent, label }, (t += 900));
        this.notify("tutorial.progress", { session_id: sid, state: "STEP_DONE", step_i: i + 1, n_steps: 3, intent, label, seconds: s }, (t += 1400));
      });
      this.notify("tutorial.done", { session_id: sid, kind: "text", answer: "Đây là bản xem thử giao diện, không chạy Excel thật." }, (t += 600));
      return;
    }
    this.cb(JSON.stringify({ jsonrpc: "2.0", id, error: { code: -32601, message: `preview: ${method}` } }));
  }
}

export function createClient(): RpcClient {
  return new RpcClient(inTauri() ? new TauriTransport() : new PreviewTransport());
}
