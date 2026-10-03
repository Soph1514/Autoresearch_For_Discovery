# Run API and event contract

Version 1 is the authoritative contract between orchestration and the research
UI. JSON field names are camelCase. A future incompatible shape increments
`schemaVersion`; consumers reject versions they do not understand.

## Snapshot and events

`GET /api/runs/{runId}` returns:

```json
{
  "schemaVersion": 1,
  "run": {},
  "ideas": [],
  "experiments": [],
  "elites": [],
  "logs": [],
  "generationFailures": [],
  "sequence": 0
}
```

Every SSE event has `schemaVersion`, `runId`, a unique `eventId`, a strictly
increasing per-run `sequence`, an RFC 3339 `timestamp`, `type`, and `payload`.
Version 1 event types are:

- `idea_created`: a complete candidate record. Re-emission with the same ID is
  an upsert, used for lifecycle fields such as inactivity.
- `experiment_updated`: an evaluation upsert. Missing metrics remain distinct
  from zero-valued metrics.
- `elite_changed`: backend-owned island/global archive membership. The UI never
  ranks candidates.
- `generation_failed`: request ID, generation, sanitized error, and measured
  input/output token usage. The generation prompt is retained in evolution
  state but is not put on the UI wire.
- `log_added`: an append-only research log record.
- `run_status_changed`: an authoritative status transition.

Parents and inspirations are separate fields. `crossover` is represented as
`merge`; it is never presented as `merge_mutation`. That operation can only be
emitted after the backend gains an explicit post-crossover mutation stage and
records the additional mutation.

The backend publishes lifecycle events through the native `EvolutionObserver`
callbacks. Invalid static candidates and provider failures therefore remain
visible without wrapping or subclassing the search engine.

## Replay and reconnect

The client first reads a snapshot and subscribes with
`GET /api/runs/{runId}/events?after={snapshot.sequence}`. `Last-Event-ID` is
also accepted; the larger cursor is used. Events with sequence at or below the
client cursor are duplicates and are ignored. A gap requires a fresh snapshot.
Negative/future cursors are rejected rather than silently losing evidence.

All pending events after the cursor are replayed in order. The stream sends
heartbeats while active and closes after terminal evidence has drained. The
browser closes its stream when it receives the terminal status event.
Development history is in memory; durable replay is step 11 of the pipeline.

## Run states and controls

States are `running`, `pausing`, `paused`, `stopping`, `stopped`, `completed`,
and `failed`. The last three are terminal.

Control routes return the acknowledged state rather than asking the UI to
predict it:

```json
{
  "schemaVersion": 1,
  "runId": "...",
  "action": "pause",
  "applied": true,
  "status": "pausing"
}
```

Pause changes `running` to `pausing`. Already-scheduled work finishes and is
committed; the loop then blocks at its native next-generation checkpoint and
emits `paused`. Resume from either `pausing` or `paused` opens that checkpoint,
which also lets a quick resume cancel a pending pause. Repeating a control that
has already reached its requested state is an idempotent acknowledgement with
`applied: false`. Incompatible non-idempotent transitions return HTTP 409.

Stop changes a nonterminal run to `stopping` and cancels the orchestration task.
Cancellation propagates through provider/evaluator awaits; completed evidence
is retained, running evaluations are marked cancelled, and the final state is
`stopped`. Production adapters must not swallow `CancelledError`. Paused time
is excluded from the run clock; draining in-flight work before `paused` is not.
