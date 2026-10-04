import { test } from "node:test";
import assert from "node:assert/strict";
import { applyEvent, type Snapshot, type ResearchEvent, type Update } from "./contracts";

const snapshot = (): Snapshot => ({
  schemaVersion: 1, sequence: 0,
  run: { id: "run", title: "Research", status: "running", startedAt: "2026-10-04" },
  ideas: [], experiments: [], elites: [], logs: [], generationFailures: [],
});
const event = (sequence: number, update: Update): ResearchEvent => ({
  ...update, schemaVersion: 1, runId: "run", eventId: `event-${sequence}`, sequence, timestamp: "2026-10-04",
});

test("replay retains failed evidence, replaces records and preserves retired elites", () => {
  const idea = { id: "seed", title: "Seed", description: "Baseline", parents: [], operation: "seed" as const, inactive: false };
  const experiment = { id: "eval", ideaId: "seed", status: "running" as const, valid: null, metrics: {}, feedback: "" };
  const elite = { ideaId: "seed", experimentId: "eval", niche: "island", current: true };
  const updates: Update[] = [
    { type: "idea_created", payload: idea },
    { type: "experiment_updated", payload: experiment },
    { type: "experiment_updated", payload: { ...experiment, status: "completed", valid: true, metrics: { score: 2 } } },
    { type: "elite_changed", payload: elite },
    { type: "elite_changed", payload: { ...elite, current: false } },
    { type: "experiment_updated", payload: { ...experiment, id: "failed", ideaId: "child", status: "failed", valid: false, feedback: "Invalid" } },
    { type: "run_status_changed", payload: { status: "stopped" } },
  ];
  const initial = snapshot();
  const events = updates.map((update, i) => event(i + 1, update));
  const final = events.reduce(applyEvent, initial);
  assert.equal(initial.sequence, 0);
  assert.equal(final.run.status, "stopped");
  assert.deepEqual(final.ideas, [idea]);
  assert.equal(final.experiments.length, 2);
  assert.equal(final.experiments[0].metrics.score, 2);
  assert.equal(final.experiments[1].valid, false);
  assert.deepEqual(final.elites, [{ ...elite, current: false }]);
  assert.equal(applyEvent(final, events[0]), final);
  assert.equal(applyEvent(initial, { ...events[0], runId: "another-run" }), initial);
  assert.throws(() => applyEvent(initial, events[1]), /gap/);
});

test("generation failures are upserted without losing usage", () => {
  const payload = { requestId: "request", generation: 1, error: "provider unavailable", inputTokens: 10, outputTokens: 2 };
  const first = applyEvent(snapshot(), event(1, { type: "generation_failed", payload }));
  const revised = { ...payload, error: "retry exhausted", outputTokens: 5 };
  const final = applyEvent(first, event(2, { type: "generation_failed", payload: revised }));
  assert.deepEqual(final.generationFailures, [revised]);
});

test("idea status updates preserve arrival order and stable graph lanes", () => {
  const a = {id: 'a', title: 'a', description: '', parents: [], operation: 'seed' as const, inactive: false};
  const b = {...a, id: 'b'};
  let state = applyEvent(snapshot(), event(1, {type: 'idea_created', payload: a}));
  state = applyEvent(state, event(2, {type: 'idea_created', payload: b}));
  state = applyEvent(state, event(3, {type: 'idea_created', payload: {...a, inactive: true}}));
  assert.deepEqual(state.ideas.map(i => i.id), ['a', 'b']);
  assert.equal(state.ideas[0].inactive, true);
});
