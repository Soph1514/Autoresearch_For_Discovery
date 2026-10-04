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
- `assessment_recorded`: advisory critic output keyed by `candidateId`; includes
  promise rating, approach, novelty note, risks, model and prompt version. It never
  changes validity or metric scores. Older snapshots may omit `assessments`.
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
Snapshots and events are persisted transactionally in SQLite. Restart marks
interrupted runs stopped and appends ordered recovery events; completed history
remains replayable.

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


## Custom preparation and run routes

Preparation request bodies use snake_case (the event wire remains camelCase).
`POST /api/formalizations` now returns a persisted `formalization_id` and the
checker-provided `check_artifact`, when available. `POST /api/contracts` accepts:

```json
{
  "formalization_id": "server-issued-id",
  "seed_program": "def solve() -> float:\n    return 1.0\n",
  "evaluation_suite_id": "your-fixed-suite-v1",
  "evaluation_cases": {"case-1": {}},
  "fitness_function_id": "autocorrelation",
  "fitness_function_version": "exact-v1",
  "alignment_reviewed": true
}
```

The example is structural; the seed and inputs must match the interface extracted
from the actual saved Lean statement. Resource fields are `case_time_seconds`,
`candidate_time_seconds`, `memory_mb`, and `max_iterations`. Defaults are 5, 60,
512, and 100000 respectively. A matching successful check artifact is mandatory.
The response contains the contract `id`, signature, metric and direction.

`POST /api/runs` accepts `{"mode":"custom", "contract_id":"...",
"max_tokens":32768, "max_time_seconds":300}` or `{"mode":"demo"}`.
Custom runs default to no overall or candidate execution time cap. Set
`max_time_seconds` and/or `enforce_execution_time_limits: true` to opt into
time limits. `max_output_tokens: null` uses the model maximum (128000 for
Opus 5.5, 64000 for Sonnet 4.6); a numeric value requests a smaller cap.
The default $50 cost ceiling, sandbox isolation and manual Stop remain active.
Custom runs resolve the contract's required fitness function and fail closed
when it is unregistered, its digest changed, the contract is incompatible, or
Docker/the worker image is unavailable. Backend `python` denotes
a custom run; `python-demo` denotes the analytic routing demo.

`GET /api/capabilities` reports configuration availability and Docker/image readiness for the built-in evaluator
(`evaluator_ready`, `evaluator_error`) plus registered `fitness_functions`.
Operator registries are checked during preparation and at run start. `GET /api/runs` lists saved runs. `GET /api/runs/{id}/artifact` exports
contracts, provenance, generation configuration, evidence, events and available
outcomes. Evaluation inputs use tagged scalar/list/tuple/mapping nodes to preserve
Python types across storage. This export includes hidden suite data and generation
prompts and belongs to the trusted operator, not the candidate sandbox.

## Synthesis sessions

Human-reviewed fitness synthesis adds **no** version-1 run event types. The run
event contract above is unchanged, because a synthesis session happens before a
run exists: there is no run ID, no snapshot and no SSE stream at that point.
Progress is read by polling `GET /api/syntheses/{id}`.

| Route | Purpose |
| --- | --- |
| `POST /api/syntheses` | Open a session against a checked formalization and start round 1. 201. |
| `GET /api/syntheses/{id}` | The session projection: state, round, budget, every round's candidates, critic and decision. |
| `POST /api/syntheses/{id}/review` | `{decision, feedback?, round_index}`. Feedback is required (20 characters) on `reject` and forbidden on `accept`. 409 when the session is not `awaiting_review` or the round index is stale. |
| `GET /api/syntheses/{id}/scorer/{slot}` | The module as `text/plain`, always an attachment with `nosniff`. It is untrusted model output and is never rendered inline. |

`POST /api/contracts` gains `synthesis_id`, mutually exclusive with
`fitness_function_id`, and answers **409** with `{"synthesis_required": true}`
when the Lean compiler reports `unsupported_formalization`. Every other compiler
stage keeps its 422. Successful preparation now returns `evidence_tier` and, for
this path, a `synthesis` block instead of `compiler`.

Details and limitations: [fitness-synthesis.md](fitness-synthesis.md).
