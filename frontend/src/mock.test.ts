import { test } from "node:test";
import assert from "node:assert/strict";
import { MockResearchClient, witness } from "./mock";
import { applyEvent, type ResearchEvent, type ProblemInput } from "./contracts";
const input: ProblemInput = {
  text: "",
  attachments: [],
  initialResults: "",
  resultFiles: [],
  mode: "demo",
};
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
test("pause drains active work; resume preserves lineage and invalid evidence", async () => {
  const c = new MockResearchClient(10);
  try {
    const run = await c.startRun(input);
    const pause = await c.pauseRun(run.id);
    assert.equal(pause.status, "pausing");
    assert.equal(pause.applied, true);
    await sleep(50);
    let s = await c.getSnapshot(run.id);
    assert.equal(s.run.status, "paused");
    assert.equal(s.ideas.length, 1);
    assert.equal(s.experiments[0].status, "completed");
    await c.resumeRun(run.id);
    await sleep(200);
    s = await c.getSnapshot(run.id);
    assert.equal(s.run.status, "completed");
    assert.equal(s.ideas.length, 7);
    assert.deepEqual(s.ideas.find((i) => i.id === "07")?.parents, ["02", "03"]);
    assert.equal(
      s.ideas.find((i) => i.id === "07")?.operation,
      "merge_mutation",
    );
    assert.equal(s.experiments.find((e) => e.ideaId === "04")?.valid, false);
    assert.ok(!s.elites.some((e) => e.ideaId === "04"));
    assert.equal(s.elites.find((e) => e.ideaId === "03")?.current, false);
    assert.equal(s.elites.find((e) => e.ideaId === "07")?.current, true);
  } finally {
    c.dispose();
  }
});
test("replay, duplicate suppression, gaps, and stop preserve consistent snapshots", async () => {
  const c = new MockResearchClient(20);
  try {
    const r = await c.startRun(input);
    const initial = await c.getSnapshot(r.id);
    assert.equal(initial.schemaVersion, 1);
    assert.deepEqual(initial.generationFailures, []);
    const events: ResearchEvent[] = [];
    const off = c.subscribe(r.id, initial.sequence, (e) => events.push(e));
    await c.stopRun(r.id);
    await sleep(60);
    const end = await c.getSnapshot(r.id);
    assert.equal(end.run.status, "stopped");
    assert.equal(end.experiments[0].status, "cancelled");
    let rebuilt = initial;
    for (const e of events) rebuilt = applyEvent(rebuilt, e);
    assert.deepEqual(rebuilt, end);
    assert.equal(applyEvent(rebuilt, events[0]), rebuilt);
    assert.throws(
      () =>
        applyEvent(initial, { ...events[0], sequence: initial.sequence + 2 }),
      /gap/,
    );
    off();
    const replay: ResearchEvent[] = [];
    c.subscribe(r.id, initial.sequence, (e) => replay.push(e))();
    assert.deepEqual(replay, events);
  } finally {
    c.dispose();
  }
});
test("Pigou witness reaches the known bound", () => {
  assert.equal(witness(1).poa, 4 / 3);
  assert.equal(witness(1).optimum, 0.75);
});

test("generation failures are upserted by request ID", async () => {
  const c = new MockResearchClient(100);
  try {
    const run = await c.startRun(input);
    const snapshot = await c.getSnapshot(run.id);
    const event: ResearchEvent = {
      schemaVersion: 1,
      runId: run.id,
      eventId: "event-failure",
      sequence: snapshot.sequence + 1,
      timestamp: new Date().toISOString(),
      type: "generation_failed",
      payload: {
        requestId: "request-1",
        generation: 1,
        error: "provider APIConnectionError",
        inputTokens: 0,
        outputTokens: 0,
      },
    };
    assert.deepEqual(applyEvent(snapshot, event).generationFailures, [event.payload]);
  } finally {
    c.dispose();
  }
});
