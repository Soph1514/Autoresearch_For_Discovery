# UI integration status

The UI bridge uses the shared evolution engine and prepared contract. The
contract now binds a complete versioned interface and immutable evaluation
suite; production preparation and sandbox adapters are still outstanding.

![Integrated pipeline](ui-pipeline.svg)

## Connected now

- React → Vite `/api` proxy → FastAPI on port 8000.
- HTTP run creation, snapshots, pause/resume/stop, and ordered SSE with replay using `Last-Event-ID`.
- Real `EvolutionLoop` and `EvolutionEngine`: generation planning, parent selection, novelty, islands, elite preservation, static rejection, and budget accounting.
- `ObservedEngine` delegates to the original engine and publishes committed state. Demo evaluator publishes started/completed attempts; static rejections are published when the engine commits the batch.
- Candidate hypotheses become titles/descriptions; source, predictions, falsification conditions, islands, and inspirations are visible in the inspector. Inspirations are separate clickable references, not parent edges.
- Actual backend generation numbers and primary metric direction are used. `crossover` maps to merge, `repair` remains repair. A merged mutation is not inferred: the backend currently has no explicit field for it.
- Current/former island elites and global best come from the engine. No UI-side ranking determines elite membership.
- Pausing drains the current batch and gates the next generator call. Stop cancels the local task. Snapshot/event history is in server memory; the browser remembers its run ID in session storage and can reconnect after refresh.

## Explicit placeholders

`ui/demo.py` supplies a prepared Pigou contract, deterministic proposals, and an analytic evaluator. The evaluator reads a restricted constant-return AST and never executes generated Python. No LLM call, sandbox, image interpretation, or Lean proof check happens in this demonstration. Token counts are simulated adapter usage. Search policy and archive decisions are real.

The main AntiAI composer calls the hosted formalization pipeline described below. Custom problems are not routed into the prepared evolution demo. The evolution API accepts only explicit demo runs; `/api/formalizations` handles custom Lean preparation. The development API binds to localhost and has no deployment authentication or durable storage; it is not a public hosting configuration.

## Remaining work / decisions

1. Production generator and sandboxed evaluator adapters implementing the existing async ports.
2. Natural-language/image input → formalization → checked Lean → contract and seed preparation. The contract now carries the complete interface; production sandbox loading remains outstanding.
3. Final wire schema and API ownership. The bridge currently emits the frontend camelCase contract; it can be revised at this boundary without changing the evolution policy.
4. A native engine observer/control interface if maintainers prefer it over the separate observation subclass. Per-provider-call concurrency, live token updates, and cancellation need adapter support.
5. Explicit short titles and crossover-plus-mutation provenance if required. Do not fabricate these fields from an operator label.
6. Persistent run storage and authenticated deployment.
7. Evolution time limits are checked between operations, not enforced as hard interruption of a stalled provider/evaluator. The development bridge excludes fully paused time through its active-time clock; production orchestration must preserve that semantic.
8. `uv.lock` was already locally modified (Python 3.12 resolution). It is tracked despite `.gitignore`. That modification was preserved and excluded from integration commits; the team should agree its Python version/lock policy. Optional UI dependencies were installed directly into the existing virtual environment without rewriting the lock.

## Run locally

Install existing project dependencies as usual, then install the additive API dependencies:

```sh
uv pip install --python .venv/bin/python 'fastapi>=0.115' 'uvicorn>=0.30'
```

Terminal 1, repository root:

```sh
PYTHONPATH=src .venv/bin/python -m uvicorn the_pigeon_holes.ui.api:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```sh
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173 and run the routing demo. `GET /api/health` identifies the real engine and demo adapters. At most one run is active and 20 runs are retained in this development server; restarting clears history.

Validation: Python suite plus bridge tests (`.venv/bin/python -m pytest -q`), frontend tests (`npm --prefix frontend test`), production build (`npm --prefix frontend run build`), and browser/HTTP integration checks. These do not establish scientific novelty or production adapter correctness.

## Hosted formalization (AntiAI integration)

The composer now calls `POST /api/formalizations`. Natural-language input uses
Qwen3-4B-Instruct-2507, then pinned Lean 4.19/Mathlib checking in a Modal worker,
with one repair attempt on checker failure. Existing Lean input bypasses generation.
Successful checks are scored by the frozen fine-tuned fidelity classifier. A review
result is displayed explicitly; it is not treated as accepted. The generator uses
the pretrained instruction model, because the frozen fine-tuned checkpoint is a
sequence classifier and cannot generate Lean. Greedy generation is configured;
only the Lean check is the deterministic validation step.

Deploy both services in the workspace that owns the classifier:

```sh
.venv/bin/modal deploy --profile arin06 research/lean-fidelity/modal_generation.py
.venv/bin/modal deploy --profile arin06 research/lean-fidelity/modal_checker.py
MODAL_PROFILE=arin06 .venv/bin/python -m uvicorn the_pigeon_holes.ui.api:app --host 127.0.0.1 --port 8000
```

The main `frontend/index.html` preserves the AntiAI paper workbench design.
The engine demonstration remains at `/engine.html`. Set `RESEARCH_API_URL` when
starting Vite if the Python API uses a port other than 8000.
For a classifier in a separate workspace, set `FIDELITY_ENDPOINT`,
`FIDELITY_TOKEN_ID`, and `FIDELITY_TOKEN_SECRET` on the backend; otherwise the
Modal SDK uses the selected profile for all three services.
The existing `lean-fidelity-api` deployment supplies fidelity scoring. The Python
backend uses authenticated Modal SDK calls with the operator's Modal credentials;
no credentials are sent to the browser. Install UI dependencies with
`uv pip install --python .venv/bin/python -e '.[ui]'`. Keep the API bound to localhost.
The Lean admission filter is conservative; this is not a public arbitrary-code service.

The original standalone demo is accessible using **Open demo page** in the header
(`/api/demo`), and **Run routing demo** retains the engine-backed demo.
Custom formalizations are returned for review; building custom evaluation suites,
seed programs, and contracts for autonomous evolution remains separate work.
