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
case inputs, fitness-function ID/version, and an alignment-review acknowledgement. Contract
preparation validates the interface and case shapes without executing generated
Python. Its saved ID can be used to start custom evolution; the seed must pass the
evaluator before candidate generation. The UI reports missing evaluator configuration.
The engine labels custom runs separately and offers a run-evidence download.

`RESEARCH_MODEL` selects the Anthropic model for extraction and generation.
The built-in registry provides `autocorrelation` version `exact-v1`:
`solve(n: int) -> list[int]`, mean `c1` minimization, with case sizes from 2 to
4096. Build the Docker worker before starting.
`RESEARCH_FITNESS_REGISTRY=module:create_registry` supplies another
operator-trusted registry; see [setup and remaining work](pipeline-next-steps.md). The checker must be redeployed
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
scores are computed independently by the host fitness function. The benchmark CLI uses a Lean placeholder;
it does not bypass the custom UI's provenance requirements. Iteration counts and
interruption of host arithmetic threads remain limitations.

The merged `assessment_recorded` event is accepted, replayed and shown as advisory
in the inspector. The CLI can enable the critic; custom UI forms now default to three bounded critic calls (the API default remains zero). Generator and critic share the run token budget.


## Verified Sidon demo (4 October 2026)

See [the run report](demo-verification.md) for actual preparation, search, exact
witness rechecks, held-out results and limitations. The checker update was deployed.
The existing-Lean path passes with the reviewed Sidon specification; automatic
Qwen formalization still required assistance for this problem. The workbench
supports saved `?formalization=` links, and the engine supports `?run=` links,
saved history, exact witness plots and model/token provenance. Completed snapshots
survive restart unchanged. `scripts/export_run.py` and `scripts/import_run.py`
provide a replayable evidence bundle without executing archived source.

## Human-paced DAG updates

Lineage now uses a parent-first topological order and stable grid positions.
Every child is below all its parents, including merges whose supplied generation
matches a parent. Missing or cyclic ancestry is withheld with a visible warning.
Independent restarts remain disconnected and retain their generation row.

Live arrivals reveal one card every two seconds by default. The viewer can choose
one/four seconds, pause reveals, advance one idea, replay the saved tree, or show
all. Selecting an idea pauses reveals for inspection. These controls affect only
the graph: backend execution, numerical results, counters and logs stay live.
Saved runs open fully expanded; replay shows current saved evidence rather than
pretending to replay historical evaluation timings. Existing nodes do not move
when new candidates arrive; automatic framing can gently pull back.

Validation: ten frontend tests pass, including burst ordering, two-parent merges,
stable positions, and unresolved/cyclic ancestry. Production build passes.
Browser QA on the 18-node Sidon run checked two-second arrivals, pause holding the
node count, one-step advancement, full-tree restoration, and no console errors.

## Literature-informed reasoning and cost controls

Custom research defaults to Opus 5.5 at high reasoning effort and a US$50 API cap.
The workbench exposes the cap, model, time/token limits, and opening literature
review. Sonnet 4.6 performs up to three web searches and advisory reviews. If the
search response is truncated, one bounded synthesis call completes the review.
Sources and queries are saved and visible in the UI. Retrieved material is treated
as untrusted evidence; it does not change the contract, fixed suite, evaluator,
parent selection, novelty archive, independent restarts or validity decisions.

The shared provider ledger reserves input, maximum output and search charges
before concurrent requests. Unknown billing after an exception/cancellation keeps
its reservation. Search calls conservatively reserve one full model context per
possible internal turn. Standard API prices are pinned in `llm/budget.py`; unknown
models fail closed. The cap includes literature, generation and critic calls, but
excludes existing formalization/interface preparation, hosting, taxes and earlier
runs. The UI reports estimated and committed costs separately; it is not an invoice.

Completed/failed/stopped runs automatically select their best valid candidate,
mark its card BEST with a gold border, and show its score and candidate ID in a
final-result line. The label explicitly refers to this run. Legacy and registered
fitness evidence formats both render witness plots and export exact certificates.
