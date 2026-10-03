# Idea-tree UI and backend integration

Status: the UI is connected to the real Python evolution engine through a local FastAPI/SSE bridge, with explicit demo generator/evaluator ports. See `docs/ui-integration-status.md` for current behavior and remaining gaps. The sections below retain the original proposed contract; arbitrary problem upload and production adapters are not connected.

## Ownership and stack

- Build the UI in `frontend/` using React, TypeScript, Vite, React Flow, Dagre for graph layout, and plain CSS. Use a React reducer and context for frontend state.
- Frontend ownership covers problem input, graph rendering, candidate inspection, research logs, run controls, and the mock research client.
- Backend ownership covers problem interpretation, LLM calls, asyncio orchestration, execution, judging, archive decisions, artifacts, and persistence. The UI does not run research or decide validity and elite membership.
- Keep frontend work separate from teammates' Python modules. Agree on a backend API/event-adapter owner and reuse existing pipeline models where possible.

## Screen structure

- **Problem composer:** natural-language text, blackboard or handwritten-work images, documents, and optional initial results. Preview attachments and allow removal. Require text or an attachment.
- **Lab controls:** show running, pausing, paused, stopping, completed, or failed states. Reflect backend acknowledgments rather than assuming a command succeeded.
- **Main idea graph:** short titles, operation labels, experiment status, and elite markers. Support multiple active candidates, pan/zoom, fit-to-view, and optional follow-latest behavior.
- **Idea details:** show the hypothesis, description, parents, additional mutation, experiment attempts, metrics, validity evidence, feedback, and elite history when a node is clicked. Retrieve stored descriptions rather than generating them on click.
- **Research log:** append timestamped updates; clicking a related entry selects its idea. Auto-scroll only when the reader is already at the bottom.
- Preserve all candidates. Grey inactive candidates and optionally compact their boxes. Keep failure, inactivity, and former-elite status distinct. Preserve the viewport when updates arrive.

## Shared data

- **Run:** stable ID, status, problem summary, timestamps, and optional budget.
- **Idea:** stable ID, title, description, parent IDs, operation, mutation description, and creation time.
- **Experiment:** stable ID, idea ID, status, validity, metrics, feedback, and optional artifact references. An idea can have multiple attempts.
- **Elite membership:** idea/experiment reference, niche, and current/former membership. A niche is an explicitly defined selection category, such as strongest bound or simplest construction; the backend owns its criteria. Start with the main objective and add categories only when agreed.
- **Log entry:** stable ID, timestamp, category, message, and optional idea/experiment references.

Use explicit operations: `seed`, `exploration`, `mutation`, `merge`, and `merge_mutation`. A merge records both parents. A merge plus mutation also describes the extra change beyond combining them. Lineage is a directed acyclic graph, even though the screen presents a tree-like layout. Keep execution status separate from elite membership.

## Client boundary and proposed routes

Components use a `ResearchClient` interface. Implement `MockResearchClient` first, then replace it with an HTTP/SSE client without changing the components.

| Client operation | Proposed backend route | Purpose |
| --- | --- | --- |
| `startRun(input)` | `POST /api/runs` | Submit problem text, attachments, and initial results; return the run ID and initial status. |
| `getSnapshot(runId)` | `GET /api/runs/{id}` | Return current run, ideas, experiments, archive membership, logs, and last event sequence. |
| `subscribe(runId, afterSequence)` | `GET /api/runs/{id}/events?after={sequence}` | Stream updates through server-sent events (SSE); return an unsubscribe handle locally. |
| `pauseRun(runId)` | `POST /api/runs/{id}/pause` | Request a pause and acknowledge acceptance. |
| `resumeRun(runId)` | `POST /api/runs/{id}/resume` | Request resumed scheduling. |
| `stopRun(runId)` | `POST /api/runs/{id}/stop` | Request termination; backend reports when stopped. |

Use multipart form data for text plus file uploads. Agree file limits, accepted formats, error responses, stop semantics, and any artifact retrieval routes with the backend team. Keep LLM credentials in the backend.

## Events and asyncio

An event envelope is the metadata around an update: schema version, run ID, unique event ID, per-run sequence number, timestamp, event type, and payload. Proposed event types include `idea_created`, `experiment_updated`, `elite_changed`, `log_added`, and `run_status_changed`.

```json
{
  "schema_version": 1,
  "run_id": "run_004",
  "event_id": "evt_028",
  "sequence": 28,
  "timestamp": "2026-10-03T12:00:00Z",
  "type": "experiment_updated",
  "payload": {
    "experiment_id": "exp_009",
    "idea_id": "idea_007",
    "status": "completed",
    "valid": true,
    "metrics": { "poa": 1.333333 }
  }
}
```

- Concurrent asyncio tasks may finish in any order. Correlate updates using IDs, never arrival position or the selected node.
- A backend event publisher assigns a single ordered sequence per run. Ignore duplicate events; recover sequence gaps by retrieving a snapshot.
- A snapshot includes its last applied sequence. Replay events after that sequence so updates between snapshot retrieval and subscription are not lost. If replay is unavailable, require a fresh snapshot.
- Proposed pause policy: stop scheduling new experiments, let active work finish, then emit `paused`. Show `pausing` while work drains. Confirm this policy with the orchestration owner.
- Preserve failed attempts and distinguish missing/pending metrics from zero. The backend remains authoritative for run state, validity, and elite decisions.

## Placeholders for the first implementation

The mock client emits deterministic asynchronous events for the Pigou routing example: seed, concurrent attempts, weaker/failed attempts, two-parent merge, merge plus mutation, elite changes, and completion. It supports snapshots, subscriptions, and pause/resume/stop through the same client interface.

- Label demo runs clearly. The example rediscovers the known 4/3 affine-routing bound; it is not a new research result. Mathematical witness values are separate from scripted search decisions and timings.
- Keep uploaded files in browser memory and preview images locally. Do not claim OCR, document interpretation, execution, or LLM generation.
- Starting the prepared example must explicitly select the demo; do not present its results as answers to an arbitrary uploaded problem.
- Use prepared descriptions and feedback. No API keys or Python service are required for the mock.
- Mock state lasts for the browser session and resets on refresh. Real run persistence belongs to the backend; later load a snapshot and reconnect the event stream.

## Local development and integration

Run `npm install` and `npm run dev` from `frontend/`. Vite normally serves the UI at `http://localhost:5173`; use the URL printed by the process.

For the mock, only the frontend terminal is needed. For real integration, run the Python backend in a second terminal using the command supplied by its owner, typically on port 8000. Configure Vite to proxy `/api` requests, including SSE, to that service:

```text
Browser :5173 -> Vite /api proxy -> Python API :8000 -> asyncio pipeline
Browser       <- SSE updates   <- event publisher <- research results
```

The Vite proxy is development-only. A deployed version will need equivalent API routing. Long-lived SSE responses must not be buffered by the proxy.

## Delivery order and checks

1. Agree frontend types and backend ownership; implement the mock client and fixture.
2. Build the composer, graph, inspector, research log, and acknowledged run controls.
3. Check parent edges, merge/mutation labels, concurrent updates, duplicate handling, snapshot recovery, pause/resume, input previews, and viewport preservation.
4. Align actual backend payloads, add the HTTP/SSE adapter, and verify one complete run across both services.

Keep checks focused; no TDD requirement. Do not introduce a second orchestration layer or browser-side experiment database.
