// Contracts of the engine's JSON-RPC surface (SPEC §11, engine/kem_engine/rpc/server.py).

export interface Progress {
  session_id: string;
  state: string; // PLAN | SETUP | GROUND | CAPTURE | ACT | VERIFY | STEP_DONE | RECOVER | TEARDOWN | WRITE | DONE | CANCELLED
  step_i?: number;
  n_steps?: number;
  message?: string;
  label?: string; // real UIA name of the element acted on
  intent?: string;
  seconds?: number;
}

export interface CreateResult {
  session_id: string;
  kind: "tutorial" | "text" | "error";
  answer?: string | null;
  tutorial_id?: string | null;
  status?: "ok" | "partial" | "failed" | "cancelled" | null;
  path?: string | null;
  llm_calls?: number;
  seconds?: number;
  writer_source?: string | null; // "llm_pending": template text now, tutorial.updated follows
}

export interface TutorialStep {
  id: number;
  heading: string;
  body: string;
  tip?: string | null;
  image?: string | null;
  result_image?: string | null;
  demonstrated: boolean;
}

export interface TraceStep {
  id: number;
  intent: string;
  element_name?: string | null;
  control_type?: string | null;
  verified: boolean;
  attempts: number;
  grounding_score?: number | null;
  inserted_reason?: string | null;
  error?: string | null;
  verify_note?: string | null;
}

export interface Tutorial {
  tutorial_id: string;
  title: string;
  intro: string;
  steps: TutorialStep[];
  outro: string;
  env_label: string;
  status: "ok" | "partial" | "failed" | "cancelled";
  dir: string;
  trace?: { llm_calls?: number; user_file?: boolean; steps: TraceStep[] };
}

export interface TutorialMeta {
  tutorial_id: string;
  title: string;
  status: string;
  path: string;
  created: number;
  llm_calls: number;
  source: string;
}

export interface SystemCheck {
  excel: { ok: boolean; version?: string; build?: string; ui_lang?: string; error?: string };
  model: { ok: boolean; provider?: string; model?: string; missing?: string[]; error?: string; note?: string };
}

export interface Settings {
  provider?: "ollama" | "gemini";
  has_key: { gemini: boolean };
}

export interface CloudCheck {
  ok: boolean;
  model?: string;
  seconds?: number;
  error?: string;
}
