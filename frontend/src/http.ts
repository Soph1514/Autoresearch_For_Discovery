import type {
  ResearchClient,
  ProblemInput,
  Run,
  Snapshot,
  ResearchEvent,
  ControlAcknowledgement,
} from "./contracts";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch("/api" + path, init);
  } catch {
    throw Error("Python API unavailable. Start the backend on localhost:8000.");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw Error(
      typeof body?.detail === "string"
        ? body.detail
        : `API request failed (${response.status}). Is the Python backend running?`,
    );
  }
  return response.json() as Promise<T>;
}
export class HttpResearchClient implements ResearchClient {
  async startRun(input: ProblemInput): Promise<Run> {
    if (
      input.mode !== "demo" ||
      input.attachments.length ||
      input.resultFiles.length
    )
      throw Error("Only the explicit routing demo is connected.");
    return request("/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "demo" }),
    });
  }
  async getSnapshot(id: string): Promise<Snapshot> {
    const snapshot = await request<Snapshot>("/runs/" + encodeURIComponent(id));
    if (
      snapshot.schemaVersion !== 1 ||
      snapshot.run?.id !== id ||
      !Number.isInteger(snapshot.sequence) ||
      !Array.isArray(snapshot.generationFailures)
    )
      throw Error("Unsupported research snapshot; refresh the application.");
    return snapshot;
  }
  subscribe(
    id: string,
    after: number,
    listener: (event: ResearchEvent) => void,
    onConnection?: (error: string | null) => void,
  ) {
    const stream = new EventSource(
      `/api/runs/${encodeURIComponent(id)}/events?after=${after}`,
    );
    stream.onopen = () => onConnection?.(null);
    stream.onerror = () =>
      onConnection?.(
        "Research stream disconnected; reconnecting. If the backend restarted, start a new demo.",
      );
    stream.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data);
        if (
          event.schemaVersion !== 1 ||
          event.runId !== id ||
          !Number.isInteger(event.sequence) ||
          !event.eventId ||
          !event.payload ||
          ![
            "idea_created",
            "experiment_updated",
            "elite_changed",
            "log_added",
            "generation_failed",
            "run_status_changed",
          ].includes(event.type)
        )
          throw Error("Unsupported research event");
        listener(event as ResearchEvent);
        if (
          event.type === "run_status_changed" &&
          ["stopped", "completed", "failed"].includes(event.payload.status)
        )
          stream.close();
      } catch {
        stream.close();
        onConnection?.(
          "Invalid research event received; reload to retrieve a fresh snapshot.",
        );
      }
    };
    return () => stream.close();
  }
  async pauseRun(id: string) {
    return request<ControlAcknowledgement>(`/runs/${encodeURIComponent(id)}/pause`, {
      method: "POST",
    });
  }
  async resumeRun(id: string) {
    return request<ControlAcknowledgement>(`/runs/${encodeURIComponent(id)}/resume`, {
      method: "POST",
    });
  }
  async stopRun(id: string) {
    return request<ControlAcknowledgement>(`/runs/${encodeURIComponent(id)}/stop`, {
      method: "POST",
    });
  }
}
