import { useEffect, useState } from "react";
import { backendUrl } from "./config";
import type { GenState } from "./useGenerate";
import { PHASE_LABEL, PHASE_ORDER } from "./types";

export function GameFrame({ state }: { state: GenState }) {
  if (state.webRel) {
    return (
      <div className="relative h-full w-full bg-black">
        <iframe
          src={backendUrl(`/${state.webRel}`)}
          className="h-full w-full bg-black"
          allow="autoplay; fullscreen; gamepad"
          title="game"
        />
        {Object.keys(state.controls).length > 0 && (
          <div className="pointer-events-none absolute right-3 top-3 max-w-sm rounded border border-neutral-700/80 bg-neutral-950/80 p-2 shadow-lg backdrop-blur">
            <div className="text-[11px] font-medium uppercase tracking-wide text-neutral-400">
              Controls
            </div>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {Object.entries(state.controls).map(([action, input]) => (
                <span
                  key={action}
                  className="rounded bg-neutral-800/90 px-2 py-1 text-xs text-neutral-100"
                >
                  <span className="capitalize text-neutral-400">{action}</span>: {input}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
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
            2D about 10 min · 3D about 15 min
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
