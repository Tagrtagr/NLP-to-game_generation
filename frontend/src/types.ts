export type PhaseName = "design" | "assets" | "synthesize" | "build" | "qa";
export type Status = "start" | "progress" | "done" | "error";

export type PhaseEvent = {
  phase: PhaseName;
  step: string;
  status: Status;
  detail?: string;
  payload?: Record<string, unknown>;
};

export const PHASE_ORDER: PhaseName[] = [
  "design",
  "assets",
  "synthesize",
  "build",
  "qa",
];

export const PHASE_LABEL: Record<PhaseName, string> = {
  design: "Design",
  assets: "Assets",
  synthesize: "Code",
  build: "Build",
  qa: "QA",
};
