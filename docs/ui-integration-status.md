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

The problem composer remains a local preview. Arbitrary uploads are not routed into the prepared demo. The API accepts only explicit demo runs. The development API binds to localhost and has no deployment authentication or durable storage; it is not a public hosting configuration.

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
