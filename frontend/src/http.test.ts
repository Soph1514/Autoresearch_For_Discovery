import { test } from "node:test";
import assert from "node:assert/strict";
import { HttpResearchClient } from "./http";

const client = new HttpResearchClient();

test("real HTTP client starts the explicit demo and sends controls to the backend", async t => {
  const calls: [string, RequestInit | undefined][] = [];
  t.mock.method(globalThis, "fetch", async (path: string, init?: RequestInit) => {
    calls.push([path, init]);
    return Response.json({ id: "run", status: "paused", applied: true });
  });
  assert.equal((await client.startDemo()).id, "run");
  assert.equal((await client.pauseRun("run/id")).status, "paused");
  await client.resumeRun("run/id");
  await client.stopRun("run/id");
  assert.deepEqual(calls.map(([path]) => path), ["/api/runs", "/api/runs/run%2Fid/pause", "/api/runs/run%2Fid/resume", "/api/runs/run%2Fid/stop"]);
  assert.ok(calls.every(([, init]) => init?.method === "POST"));
  assert.deepEqual(JSON.parse(calls[0][1]!.body as string), { mode: "demo" });
});

test("HTTP errors and incompatible snapshots surface without simulated results", async t => {
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json({ detail: "Evaluator unavailable" }, { status: 503 }));
  await assert.rejects(client.startDemo(), /Evaluator unavailable/);
  fetch.mock.mockImplementation(async () => { throw Error("offline"); });
  await assert.rejects(client.startDemo(), /Python API unavailable/);
  fetch.mock.mockImplementation(async () => Response.json({ schemaVersion: 2, run: { id: "run" } }));
  await assert.rejects(client.getSnapshot("run"), /Unsupported research snapshot/);
});

test("SSE uses the replay cursor, accepts critic updates and closes on completion or malformed data", t => {
  class Stream {
    static latest: Stream;
    closed = false;
    onopen: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onmessage: ((message: { data: string }) => void) | null = null;
    constructor(readonly url: string) { Stream.latest = this; }
    close() { this.closed = true; }
    send(value: unknown) { this.onmessage?.({ data: JSON.stringify(value) }); }
  }
  const original = globalThis.EventSource;
  globalThis.EventSource = Stream as unknown as typeof EventSource;
  t.after(() => { globalThis.EventSource = original; });
  const received: string[] = [], errors: (string | null)[] = [];
  client.subscribe("run/id", 4, event => received.push(event.type), error => errors.push(error));
  const stream = Stream.latest;
  assert.equal(stream.url, "/api/runs/run%2Fid/events?after=4");
  stream.onopen?.();
  assert.equal(errors.at(-1), null);
  const envelope = { schemaVersion: 1, runId: "run/id", sequence: 5, eventId: "event" };
  stream.send({ ...envelope, type: "assessment_recorded", payload: { candidateId: "candidate" } });
  assert.equal(stream.closed, false);
  stream.send({ ...envelope, sequence: 6, type: "run_status_changed", payload: { status: "completed" } });
  assert.deepEqual(received, ["assessment_recorded", "run_status_changed"]);
  assert.equal(stream.closed, true);
  const unsubscribe = client.subscribe("run/id", 6, () => assert.fail("Invalid event delivered"), error => errors.push(error));
  Stream.latest.send({ ...envelope, type: "unknown", payload: {} });
  assert.equal(Stream.latest.closed, true);
  assert.match(errors.at(-1)!, /Invalid research event/);
  unsubscribe();
});
