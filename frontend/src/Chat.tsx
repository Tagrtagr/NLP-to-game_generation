import { useState, type FormEvent } from "react";
import { PhaseCard } from "./PhaseCard";
import { PHASE_ORDER } from "./types";
import type { GenState } from "./useGenerate";

const PROMPT_EXAMPLES = [
  "a cozy 2D platformer where a cat collects yarn balls in a moonlit bakery",
  "a top-down 2D arcade game where a gardener dodges slimes and gathers seeds",
  "a 3D third-person explorer where a robot crosses floating islands to reach a beacon",
];

export function Chat({
  state,
  onSubmit,
  onCancel,
}: {
  state: GenState;
  onSubmit: (prompt: string) => void;
  onCancel: () => void;
}) {
  const [prompt, setPrompt] = useState("");

  function submit(e: FormEvent) {
    e.preventDefault();
    const p = prompt.trim();
    if (!p || state.running) return;
    onSubmit(p);
  }

  return (
    <aside className="w-2/5 min-w-[380px] max-w-[560px] border-r border-neutral-800 flex flex-col">
      <div className="p-4 border-b border-neutral-800">
        <h1 className="text-lg font-semibold">Godot Agent</h1>
        <p className="text-xs text-neutral-400 mt-1">
          Describe a game. Watch it build. Play it.
        </p>
      </div>

      <div className="flex-1 overflow-auto p-4 space-y-2">
        {Object.keys(state.controls).length > 0 && (
          <div className="rounded border border-neutral-800 bg-neutral-900/50 p-3">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-medium">Controls</h2>
              {state.template && (
                <span className="text-[11px] text-neutral-500">{state.template}</span>
              )}
            </div>
            <div className="mt-2 grid grid-cols-2 gap-1.5">
              {Object.entries(state.controls).map(([action, input]) => (
                <div
                  key={action}
                  className="flex items-center justify-between gap-2 rounded bg-neutral-950/70 px-2 py-1.5"
                >
                  <span className="text-xs capitalize text-neutral-400">{action}</span>
                  <span className="text-xs font-medium text-neutral-100">{input}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {PHASE_ORDER.map((p) => (
          <PhaseCard
            key={p}
            phase={p}
            state={state.phases[p]}
            assets={p === "assets" ? state.assets : undefined}
          />
        ))}

        {state.budgetUsed > 0 && (
          <div className="text-xs text-amber-400/80 px-1">
            Repair budget: {state.budgetUsed}/3 used
            {state.budgetTrace.length > 0 && ` (${state.budgetTrace.join(", ")})`}
          </div>
        )}

        {state.error && (
          <div className="text-xs text-rose-400 px-1">Error: {state.error}</div>
        )}
      </div>

      <form onSubmit={submit} className="p-3 border-t border-neutral-800 space-y-2">
        <div className="space-y-2">
          <div className="flex flex-wrap gap-1.5">
            {PROMPT_EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                disabled={state.running}
                onClick={() => setPrompt(example)}
                className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-left text-[11px] leading-snug text-neutral-400 hover:border-neutral-700 hover:text-neutral-200 disabled:opacity-50"
              >
                {example}
              </button>
            ))}
          </div>
          <p className="text-[11px] leading-snug text-neutral-500">
            Best results: a 2D or 3D style, a clear hero, one verb, an object, and a place.
          </p>
        </div>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
          placeholder="a [2D or 3D] [style] game where [hero] [verb] [object] in [place]"
          disabled={state.running}
          className="w-full resize-none rounded bg-neutral-900 border border-neutral-800 p-2 text-sm focus:outline-none focus:border-neutral-600 disabled:opacity-50"
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e);
          }}
        />
        <div className="text-[11px] text-neutral-500">Generation time: 2D about 10 min · 3D about 15 min</div>
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={state.running || !prompt.trim()}
            className="flex-1 rounded bg-amber-500 text-neutral-950 text-sm font-medium py-2 hover:bg-amber-400 disabled:bg-neutral-800 disabled:text-neutral-500"
          >
            {state.running ? "Generating…" : "Generate"}
          </button>
          {state.running && (
            <button
              type="button"
              onClick={onCancel}
              className="rounded border border-neutral-700 text-sm px-3 hover:bg-neutral-900"
            >
              Cancel
            </button>
          )}
        </div>
      </form>
    </aside>
  );
}
