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
        <div className="mx-auto h-10 w-10 rounded-full border-2 border-neutral-800 border-t-amber-400 animate-spin" hidden={!state.running} />
        <div className="text-sm">{label}</div>
      </div>
    </div>
  );
}
