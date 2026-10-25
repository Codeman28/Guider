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
  example?: { text: string; image?: string | null } | null;
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
  bytes?: number; // disk used by the tutorial's folder (screenshots + text)
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

// Training area (ADR-0004, developer build only)
export interface TrainStatus {
  available: boolean;
  model?: string;
  cloud?: boolean;
  research?: boolean;
  running?: boolean;
  job_id?: string | null;
}

export interface TrainProgress {
  job_id: string;
  phase: "read" | "research" | "think" | "demo" | "skip" | string;
  message: string;
  done: number;
  total: number;
}

export interface TrainSourceEntry {
  kind: string;
  name: string;
  ref: string;
  date: string;
  summary: string;
  added: number;
  merged: number;
  pending: number;
  notes: number;
  skipped?: boolean;
}

export interface TrainDone {
  job_id: string;
  ok: boolean;
  error?: string;
  model?: string;
  sources?: TrainSourceEntry[];
  chunks?: number;
  relevant?: number;
  tasks_found?: number;
  added?: number;
  merged?: number;
  pending?: number;
  rejected?: number;
  notes_added?: number;
  notes_merged?: number;
  cancelled?: boolean;
  seconds?: number;
  llm_calls?: number;
}

export interface TrainMemory {
  apps: Record<string, { cards: { id: string; title: string; source: string }[]; extends: number; pending: { id: string; title: string; reason: string }[] }>;
  notes: number;
  recent_notes: { id: string; app: string; topic: string; fact: string; sources: string[] }[];
  sources: TrainSourceEntry[];
}

export interface TrainAnswer {
  answer: string;
  citations: { n: number; text: string; source: string }[];
  model?: string;
}
