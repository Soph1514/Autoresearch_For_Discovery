export type Status =
  | "running"
  | "pausing"
  | "paused"
  | "stopping"
  | "stopped"
  | "completed"
  | "failed";
export interface Run {
  id: string;
  title: string;
  status: Status;
  startedAt: string;
  endedAt?: string;
  metricName?: string;
  direction?: "maximize" | "minimize";
  backend?: "python-demo" | "python";
  contract?: Record<string, string | number>;
}
export interface Idea {
  id: string;
  title: string;
  description: string;
  parents: string[];
  operation:
    | "seed"
    | "exploration"
    | "mutation"
    | "merge"
    | "merge_mutation"
    | "repair";
  mutation?: string;
  inactive: boolean;
  inspirations?: string[];
  island?: string | null;
  generation?: number;
  predictedEffect?: string;
  falsificationCondition?: string;
  sourceCode?: string;
  parameters?: Record<string, number>;
}
export interface Experiment {
  id: string;
  ideaId: string;
  status: "running" | "completed" | "failed" | "cancelled";
  valid: boolean | null;
  metrics: Record<string, number>;
  feedback: string;
}
export interface Elite {
  ideaId: string;
  experimentId: string;
  niche: string;
  current: boolean;
}
export interface Log {
  id: string;
  timestamp: string;
  category: string;
  message: string;
  ideaId?: string;
}
export interface GenerationFailure {
  requestId: string;
  generation: number;
  error: string;
  inputTokens: number;
  outputTokens: number;
}
export interface Assessment {
  candidateId: string;
  promiseRating: number;
  approachSummary: string;
  noveltyNote: string;
  riskFlags: string[];
  model: string;
  promptVersion: string;
}
export interface ControlAcknowledgement {
  schemaVersion: 1;
  runId: string;
  action: "pause" | "resume" | "stop";
  applied: boolean;
  status: Status;
}
export type Update =
  | { type: "assessment_recorded"; payload: Assessment }
  | { type: "idea_created"; payload: Idea }
  | { type: "experiment_updated"; payload: Experiment }
  | { type: "elite_changed"; payload: Elite }
  | { type: "log_added"; payload: Log }
  | { type: "generation_failed"; payload: GenerationFailure }
  | {
      type: "run_status_changed";
      payload: { status: Status; endedAt?: string };
    };
export type ResearchEvent = Update & {
  schemaVersion: 1;
  runId: string;
  eventId: string;
  sequence: number;
  timestamp: string;
};
export interface Snapshot {
  schemaVersion: 1;
  run: Run;
  ideas: Idea[];
  experiments: Experiment[];
  elites: Elite[];
  logs: Log[];
  generationFailures: GenerationFailure[];
  assessments?: Assessment[];
  sequence: number;
}
export interface ResearchClient {
  startDemo(): Promise<Run>;
  getSnapshot(id: string): Promise<Snapshot>;
  subscribe(
    id: string,
    after: number,
    listener: (e: ResearchEvent) => void,
    onConnection?: (error: string | null) => void,
  ): () => void;
  pauseRun(id: string): Promise<ControlAcknowledgement>;
  resumeRun(id: string): Promise<ControlAcknowledgement>;
  stopRun(id: string): Promise<ControlAcknowledgement>;
}
export function applyEvent(s: Snapshot, e: ResearchEvent): Snapshot {
  if (e.runId !== s.run.id || e.sequence <= s.sequence) return s;
  if (e.sequence !== s.sequence + 1) throw Error("Event sequence gap");
  const n = { ...s, sequence: e.sequence };
  switch (e.type) {
    case "assessment_recorded":
      return {...n, assessments: [...(s.assessments || []).filter(a => a.candidateId !== e.payload.candidateId), e.payload]};
    case "idea_created":
      return {
        ...n,
        ideas: [...s.ideas.filter((i) => i.id !== e.payload.id), e.payload],
      };
    case "experiment_updated":
      return {
        ...n,
        experiments: [
          ...s.experiments.filter((i) => i.id !== e.payload.id),
          e.payload,
        ],
      };
    case "elite_changed":
      return {
        ...n,
        elites: [
          ...s.elites.filter(
            (i) =>
              !(i.ideaId === e.payload.ideaId && i.niche === e.payload.niche),
          ),
          e.payload,
        ],
      };
    case "log_added":
      return { ...n, logs: [...s.logs, e.payload] };
    case "generation_failed":
      return {
        ...n,
        generationFailures: [
          ...s.generationFailures.filter(
            (failure) => failure.requestId !== e.payload.requestId,
          ),
          e.payload,
        ],
      };
    case "run_status_changed":
      return { ...n, run: { ...s.run, ...e.payload } };
  }
}
