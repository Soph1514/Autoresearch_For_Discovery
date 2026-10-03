# UI integration

The AntiAI workbench prepares Lean; the separate routing demo runs the evolution
engine. Custom formalizations do not yet start autonomous evolution.

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
SSE supports ordered replay and snapshot recovery. History survives browser refresh,
but not a backend restart. The local server retains at most 20 runs and permits one
active evolution run. See the [wire contract](api-events.md) for details.

## Setup and remaining work

Use the [frontend setup](../frontend/README.md) to run locally and the
[model README](../research/lean-fidelity/README.md) to deploy the four Modal services
in `arin06`. Credentials stay on the backend. For a classifier in another workspace,
configure `FIDELITY_ENDPOINT`, `FIDELITY_TOKEN_ID` and `FIDELITY_TOKEN_SECRET` there.

The API is a localhost development service without authentication or durable storage.
Custom contract/seed preparation, a protected evaluator and production orchestration
remain unconnected; see [remaining work](pipeline-next-steps.md).
