import type { AssetThumb, PhaseState } from "./useGenerate";
import { PHASE_LABEL, type PhaseName } from "./types";

const STATUS_DOT: Record<PhaseState["status"], string> = {
  idle: "bg-neutral-700",
  active: "bg-amber-400 animate-pulse",
  done: "bg-emerald-500",
  error: "bg-rose-500",
};

export function PhaseCard({
  phase,
  state,
  assets,
}: {
  phase: PhaseName;
  state: PhaseState;
  assets?: AssetThumb[];
}) {
  const last = state.steps[state.steps.length - 1];
  return (
    <div className="rounded-md border border-neutral-800 bg-neutral-900/40 p-3">
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${STATUS_DOT[state.status]}`} />
        <span className="text-sm font-medium">{PHASE_LABEL[phase]}</span>
        {last && (
          <span className="text-xs text-neutral-500 ml-auto truncate">
            {last.step}
            {last.detail ? ` — ${last.detail}` : ""}
          </span>
        )}
      </div>

      {phase === "assets" && assets && assets.length > 0 && (
        <div className="mt-2 grid grid-cols-6 gap-1.5">
          {assets.map((a) => (
            <AssetTile key={a.asset_id} a={a} />
          ))}
        </div>
      )}

      {state.steps.length > 0 && (
        <details className="mt-2">
          <summary className="text-xs text-neutral-500 cursor-pointer select-none">
            {state.steps.length} event{state.steps.length === 1 ? "" : "s"}
          </summary>
          <ul className="mt-1 space-y-0.5 text-xs text-neutral-400 font-mono max-h-40 overflow-auto">
            {state.steps.map((s, i) => (
              <li key={i} className="truncate">
                <span
                  className={
                    s.status === "error"
                      ? "text-rose-400"
                      : s.status === "done"
                        ? "text-emerald-400"
                        : "text-neutral-400"
                  }
                >
                  [{s.status}]
                </span>{" "}
                {s.step}
                {s.detail ? `: ${s.detail}` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function AssetTile({ a }: { a: AssetThumb }) {
  const isImage = a.kind !== "mesh";
  const title = `${a.role} (${a.source})${a.error ? ` — ${a.error}` : ""}`;
  return (
    <div
      className={`relative aspect-square rounded bg-neutral-800 overflow-hidden border ${
        a.source === "fallback" ? "border-amber-600/60" : "border-neutral-700"
      }`}
      title={title}
    >
      {isImage ? (
        <img
          src={`/${a.rel_path}`}
          alt={a.role}
          className="h-full w-full object-cover"
          style={{ imageRendering: "pixelated" }}
        />
      ) : (
        <div className="h-full w-full grid place-items-center text-[10px] text-neutral-400">
          GLB
        </div>
      )}
      {a.source === "fallback" && (
        <span className="absolute bottom-0 right-0 bg-amber-600/80 text-[8px] px-1 leading-tight">
          fb
        </span>
      )}
    </div>
  );
}
