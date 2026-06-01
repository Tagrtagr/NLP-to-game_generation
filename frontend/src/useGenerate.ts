import { useCallback, useEffect, useRef, useState } from "react";
import { backendUrl } from "./config";
import { streamGenerate } from "./sse";
import type { PhaseEvent, PhaseName } from "./types";

export type AssetThumb = {
  asset_id: string;
  role: string;
  kind: string;
  source: "generated" | "fallback";
  rel_path: string;
  url?: string;
  error?: string;
};

export type PhaseState = {
  status: "idle" | "active" | "done" | "error";
  steps: PhaseEvent[];
};

export type GenState = {
  running: boolean;
  sessionId: string | null;
  prompt: string | null;
  webRel: string | null;
  title: string | null;
  template: string | null;
  controls: Record<string, string>;
  phases: Record<PhaseName, PhaseState>;
  assets: AssetThumb[];
  budgetUsed: number;
  budgetTrace: string[];
  error: string | null;
};

export type SavedGame = {
  session_id: string;
  title: string;
  prompt?: string | null;
  template?: string | null;
  controls: Record<string, string>;
  assets: AssetThumb[];
  web_rel: string;
  saved_at: string;
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
  prompt: null,
  webRel: null,
  title: null,
  template: null,
  controls: {},
  phases: initialPhases(),
  assets: [],
  budgetUsed: 0,
  budgetTrace: [],
  error: null,
});

export function useGenerate() {
  const [state, setState] = useState<GenState>(initialState);
  const [savedGames, setSavedGames] = useState<SavedGame[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const sidRef = useRef<string | null>(null);

  const refreshSaved = useCallback(async () => {
    const res = await fetch(backendUrl("/api/saves"));
    if (!res.ok) throw new Error(`list saves failed: ${res.status}`);
    const data = (await res.json()) as { saves?: SavedGame[] };
    setSavedGames(data.saves ?? []);
  }, []);

  useEffect(() => {
    void refreshSaved().catch(() => {});
  }, [refreshSaved]);

  const cancel = useCallback(() => {
    const sid = sidRef.current;
    if (sid) {
      void fetch(backendUrl(`/api/cancel/${sid}`), { method: "POST" }).catch(() => {});
    }
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  const start = useCallback(async (prompt: string) => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setState({ ...initialState(), prompt, running: true });

    try {
      let sawDone = false;
      for await (const ev of streamGenerate(prompt, ac.signal)) {
        if (ev.event === "session") {
          sidRef.current = ev.data;
          setState((s) => ({ ...s, sessionId: ev.data }));
          continue;
        }
        if (ev.event === "done") {
          sawDone = true;
          setState((s) => ({ ...s, running: false }));
          void refreshSaved().catch(() => {});
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
  }, [refreshSaved]);

  const saveCurrent = useCallback(async () => {
    setSaveError(null);
    const s = state;
    if (!s.sessionId || !s.webRel) {
      setSaveError("Generate a playable web build before saving.");
      return;
    }
    const res = await fetch(backendUrl("/api/saves"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: s.sessionId,
        title: s.title ?? s.prompt ?? "Untitled game",
        prompt: s.prompt,
        template: s.template,
        controls: s.controls,
        assets: s.assets,
      }),
    });
    if (!res.ok) {
      setSaveError(`save failed: ${res.status}`);
      return;
    }
    await refreshSaved();
  }, [refreshSaved, state]);

  const loadSaved = useCallback((game: SavedGame) => {
    sidRef.current = game.session_id;
    setSaveError(null);
    setState({
      ...initialState(),
      sessionId: game.session_id,
      prompt: game.prompt ?? null,
      webRel: game.web_rel,
      title: game.title,
      template: game.template ?? null,
      controls: game.controls,
      assets: game.assets,
    });
  }, []);

  return { state, start, cancel, savedGames, saveCurrent, loadSaved, saveError };
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
      url: p.url ? String(p.url) : undefined,
      error: p.error ? String(p.error) : undefined,
    };
    assets = [...assets, thumb];
  }

  let webRel = s.webRel;
  let title = s.title;
  let template = s.template;
  let controls = s.controls;
  let budgetUsed = s.budgetUsed;
  let budgetTrace = s.budgetTrace;
  if (pe.phase === "design" && pe.step === "critic" && pe.payload) {
    const p = pe.payload as Record<string, unknown>;
    const design = p.design as Record<string, unknown> | undefined;
    if (design) {
      if (typeof design.title === "string") title = design.title;
      if (typeof design.template === "string") template = design.template;
      if (design.controls && typeof design.controls === "object" && !Array.isArray(design.controls)) {
        controls = Object.fromEntries(
          Object.entries(design.controls as Record<string, unknown>).map(([key, value]) => [
            key,
            String(value),
          ]),
        );
      }
    }
  }
  if (pe.phase === "qa" && pe.step === "ready" && pe.payload) {
    const p = pe.payload as Record<string, unknown>;
    if (typeof p.web_rel === "string") webRel = p.web_rel;
    if (typeof p.budget_used === "number") budgetUsed = p.budget_used;
    if (Array.isArray(p.budget_trace)) budgetTrace = p.budget_trace.map(String);
  }

  const error =
    pe.status === "error" && pe.step === "pipeline" ? pe.detail ?? "pipeline error" : s.error;

  return { ...s, phases, assets, webRel, title, template, controls, budgetUsed, budgetTrace, error };
}
