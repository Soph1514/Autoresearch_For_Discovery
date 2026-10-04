# UI integration

The AntiAI workbench prepares Lean and can bind it to a custom research contract.
The engine page displays either the explicit routing demo or a custom run. The built-in
Docker evaluator supports autocorrelation; other families need an adapter.

## Problem preparation

Both composers accept natural-language problems or existing Lean. A problem
description is required for fidelity scoring; formal mode also requires Lean source.
Attachments are optional. Extracted text stays editable before submission.

`POST /api/attachments?filename=...` accepts raw file bytes: PNG/JPEG/WebP,
PDF (up to 10 pages), UTF-8 text/Markdown, Lean, JSON or CSV, up to 10 MB.
The backend decodes text; the hosted CPU OCR service handles images and PDFs.
Review extracted mathematical notation before submitting.

`POST /api/formalizations?stream=true` streams preparation as NDJSON:

1. Pretrained Qwen3-4B generates Lean, or the checker receives existing Lean.
2. Pinned Lean 4.19/Mathlib checks it. Failed checks feed diagnostics back into
   repairs until a check passes or the user stops; success is not guaranteed.
3. The frozen fine-tuned Qwen classifier scores fidelity to the problem.
   A review result remains review, independently of successful compilation.

There is no overall retry limit. Individual service calls have timeouts.
Stop or stream disconnection cancels the task and active Modal call.
Generation/checking service failures stop preparation; a scoring failure preserves
checked Lean for review. Only Lean checking is deterministic; repair uses sampling.

## Evolution demo

**Open demo page** opens `/engine.html`; **Run routing demo** explicitly starts
Pigou evolution. `/api/demo` retains the original scripted demo. All three pages
share `frontend/src/paper-theme.css`.

The live demo uses the real evolution loop, with deterministic proposals and an
analytic evaluator that reads restricted constant-return Python without executing
it. It does not call an LLM or check Lean. Backend events drive lineage, metrics,
elites, failures and controls; the UI never substitutes mock results on API failure.

Pause drains the active batch; resume continues scheduling; stop cancels the task.
SSE supports ordered replay and snapshot recovery. History and events are stored in SQLite and survive backend restart. Interrupted
runs are marked stopped; work is never silently resumed. The local server permits
one active evolution run. See the [wire contract](api-events.md) for details.

## Setup and remaining work

Use the [frontend setup](../frontend/README.md) to run locally and the
[model README](../research/lean-fidelity/README.md) to deploy the four Modal services
in `arin06`. Credentials stay on the backend. For a classifier in another workspace,
configure `FIDELITY_ENDPOINT`, `FIDELITY_TOKEN_ID` and `FIDELITY_TOKEN_SECRET` there.

After Lean preparation, both composers offer seed Python, evaluation suite ID,
case inputs, evaluator version, and an alignment-review acknowledgement. Contract
preparation validates the interface and case shapes without executing generated
Python. Its saved ID can be used to start custom evolution; the seed must pass the
evaluator before candidate generation. The UI reports missing evaluator configuration.
The engine labels custom runs separately and offers a run-evidence download.

`RESEARCH_MODEL` selects the Anthropic model for extraction and generation.
The default factory connects `autocorrelation-exact-v1`: `solve(n: int) -> list[int]`,
mean `c1` minimization, with case sizes from 2 to 4096. Build the Docker worker
before starting. `RESEARCH_EVALUATOR_FACTORY=module:factory` overrides this for
another trusted adapter; see [setup and remaining work](pipeline-next-steps.md). The checker must be redeployed
with its provenance response before preparing custom contracts.

`RESEARCH_STORE` defaults to `runs/research.sqlite3`. Contracts, formalizations,
source, evidence, events, settings and completed outcomes are durable. Event writes
are transactional with their snapshot. On restart, active attempts become
interrupted/stopped and remain inspectable. This is single-process orchestration:
run one Uvicorn worker. Storage retention and backups are operator responsibilities.

The default server is localhost-only. Set `RESEARCH_API_PASSWORD` (and optionally
`RESEARCH_API_USER`, default `research`) to require HTTP Basic authentication on
all API routes. Use HTTPS through a reverse proxy for a shared deployment. This
is a shared-password lab service, without per-user isolation or multi-worker scheduling.


The evaluator now enforces bounded stdout/stderr, case and candidate-suite deadlines,
and memory limits. Stop removes its container before cancellation completes. Numerical
scores are judged independently on the host. The benchmark CLI uses a Lean placeholder;
it does not bypass the custom UI's provenance requirements. Iteration counts and
interruption of host arithmetic threads remain limitations.

The merged `assessment_recorded` event is accepted, replayed and shown as advisory
in the inspector. The CLI can enable the critic; custom UI runs currently leave it off.
