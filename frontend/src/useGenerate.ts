import { useCallback, useRef, useState } from "react";
import { streamGenerate } from "./sse";
import type { PhaseEvent, PhaseName } from "./types";

export type AssetThumb = {
  asset_id: string;
  role: string;
  kind: string;
  source: "generated" | "fallback";
  rel_path: string;
  error?: string;
};

export type PhaseState = {
  status: "idle" | "active" | "done" | "error";
  steps: PhaseEvent[];
};

export type GenState = {
  running: boolean;
  sessionId: string | null;
  webRel: string | null;
  phases: Record<PhaseName, PhaseState>;
  assets: AssetThumb[];
  budgetUsed: number;
  budgetTrace: string[];
  error: string | null;
};

const initialPhases = (): Record<PhaseName, PhaseState> => ({
  design: { status: "idle", steps: [] },
  assets: { status: "idle", steps: [] },
  synthesize: { status: "idle", steps: [] },
  build: { status: "idle", steps: [] },
  qa: { status: "idle", steps: [] },
});

const initialState = (): GenState => ({
  running: false,
  sessionId: null,
  webRel: null,
  phases: initialPhases(),
  assets: [],
  budgetUsed: 0,
  budgetTrace: [],
  error: null,
});

export function useGenerate() {
  const [state, setState] = useState<GenState>(initialState);
  const abortRef = useRef<AbortController | null>(null);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  const start = useCallback(async (prompt: string) => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setState({ ...initialState(), running: true });

    try {
      let sawDone = false;
      for await (const ev of streamGenerate(prompt, ac.signal)) {
        if (ev.event === "session") {
          setState((s) => ({ ...s, sessionId: ev.data }));
          continue;
        }
        if (ev.event === "done") {
          sawDone = true;
          setState((s) => ({ ...s, running: false }));
          continue;
        }
        if (ev.event !== "phase") continue;

        let pe: PhaseEvent;
        try {
          pe = JSON.parse(ev.data) as PhaseEvent;
        } catch {
          continue;
        }
        setState((s) => applyPhase(s, pe));
      }
      if (!sawDone) {
        setState((s) => ({
          ...s,
          running: false,
          error: s.error ?? "stream closed unexpectedly (backend reload?)",
        }));
      }
    } catch (e: any) {
      if (e?.name === "AbortError") return;
      setState((s) => ({ ...s, running: false, error: String(e?.message ?? e) }));
    } finally {
      if (abortRef.current === ac) abortRef.current = null;
    }
  }, []);

  return { state, start, cancel };
}

const TERMINAL_STEP: Record<PhaseName, string> = {
  design: "critic",
  assets: "fanout",
  synthesize: "sanity",
  build: "export",
  qa: "ready",
};

function applyPhase(s: GenState, pe: PhaseEvent): GenState {
  const phases = { ...s.phases };
  const cur = phases[pe.phase];
  const isTerminalDone = pe.status === "done" && pe.step === TERMINAL_STEP[pe.phase];
  const nextStatus: PhaseState["status"] =
    pe.status === "error"
      ? "error"
      : isTerminalDone
        ? "done"
        : cur.status === "done"
          ? "done"
          : "active";
  phases[pe.phase] = { status: nextStatus, steps: [...cur.steps, pe] };

  let assets = s.assets;
  if (pe.phase === "assets" && pe.step === "asset_ready" && pe.payload) {
    const p = pe.payload as Record<string, unknown>;
    const thumb: AssetThumb = {
      asset_id: String(p.asset_id ?? ""),
      role: String(p.role ?? ""),
      kind: String(p.kind ?? ""),
      source: (p.source as AssetThumb["source"]) ?? "generated",
      rel_path: String(p.rel_path ?? ""),
      error: p.error ? String(p.error) : undefined,
    };
    assets = [...assets, thumb];
  }

  let webRel = s.webRel;
  let budgetUsed = s.budgetUsed;
  let budgetTrace = s.budgetTrace;
  if (pe.phase === "qa" && pe.step === "ready" && pe.payload) {
    const p = pe.payload as Record<string, unknown>;
    if (typeof p.web_rel === "string") webRel = p.web_rel;
    if (typeof p.budget_used === "number") budgetUsed = p.budget_used;
    if (Array.isArray(p.budget_trace)) budgetTrace = p.budget_trace.map(String);
  }

  const error =
    pe.status === "error" && pe.step === "pipeline" ? pe.detail ?? "pipeline error" : s.error;

  return { ...s, phases, assets, webRel, budgetUsed, budgetTrace, error };
}
