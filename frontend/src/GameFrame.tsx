import { useEffect, useState } from "react";
import type { GenState } from "./useGenerate";
import { PHASE_LABEL, PHASE_ORDER } from "./types";

export function GameFrame({ state }: { state: GenState }) {
  if (state.webRel) {
    return (
      <iframe
        src={`/${state.webRel}`}
        className="h-full w-full bg-black"
        allow="autoplay; fullscreen; gamepad"
        title="game"
      />
    );
  }

  const activePhase =
    PHASE_ORDER.find((p) => state.phases[p].status === "active") ??
    PHASE_ORDER.find((p) => state.phases[p].status === "idle");

  const label = state.running
    ? activePhase
      ? `Working on ${PHASE_LABEL[activePhase]}…`
      : "Starting…"
    : state.error
      ? "Error — see chat"
      : "Describe a game on the left to begin";

  return (
    <div className="h-full w-full grid place-items-center bg-neutral-950 text-neutral-500 p-8">
      <div className="text-center space-y-3">
        <div
          className="mx-auto h-10 w-10 rounded-full border-2 border-neutral-800 border-t-amber-400 animate-spin"
          hidden={!state.running}
        />
        <div className="text-sm">{label}</div>
        {state.running && <Elapsed running={state.running} />}
        {state.running && (
          <div className="text-xs text-neutral-600">
            2–3 min typical; up to ~5 min with repairs
          </div>
        )}
      </div>
    </div>
  );
}

function Elapsed({ running }: { running: boolean }) {
  const [secs, setSecs] = useState(0);
  useEffect(() => {
    if (!running) return;
    setSecs(0);
    const start = performance.now();
    const id = window.setInterval(
      () => setSecs(Math.floor((performance.now() - start) / 1000)),
      1000,
    );
    return () => window.clearInterval(id);
  }, [running]);
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return (
    <div className="text-xs text-neutral-500 tabular-nums">
      {m}:{s.toString().padStart(2, "0")} elapsed
    </div>
  );
}
