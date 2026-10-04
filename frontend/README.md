# AntiAI frontend

Start the backend from the repository root:

```sh
uv pip install --python .venv/bin/python -e '.[ui]'
MODAL_PROFILE=arin06 PYTHONPATH=src .venv/bin/python -m uvicorn the_pigeon_holes.ui.api:app --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open the URL Vite prints (normally http://127.0.0.1:5173).
The workbench accepts natural-language or existing Lean problems, with optional
attachments. Hosted preparation requires Modal access to `arin06` and its
[deployed services](../research/lean-fidelity/README.md).
**Open demo page** opens `/engine.html`; its **Run routing demo** needs no model
credentials. The original scripted demo remains at `/api/demo`.

Vite proxies `/api` to port 8000. For another backend port, set
`RESEARCH_API_URL=http://127.0.0.1:8002` when starting Vite. Keep the API on localhost.
See [current behavior and limitations](../docs/ui-integration-status.md).

The workbench and demos share `src/paper-theme.css`. The engine graph uses React
Flow and Dagre; backend snapshots and SSE drive its state. Frontend tests exercise
the HTTP client and event reducer; lifecycle behavior is tested against the Python
engine. Auto overview yields to manual pan/zoom; faded candidates stay inspectable.

```sh
npm test
npm run build
```

## Custom research

Set `RESEARCH_MODEL` and `ANTHROPIC_API_KEY` on the backend. The built-in registry supports six problem families; new problems can use the Lean compiler. Build its worker with
`docker build -t the-pigeon-holes/candidate-worker:v1 docker/worker` from the
repository root. No factory environment variable is needed for this family;
see [setup and remaining work](../docs/pipeline-next-steps.md) for custom adapters. Redeploy the updated
`research/lean-fidelity/modal_checker.py` so successful checks include provenance.

After formalization, choose the problem family, enter fixed case inputs, and click
**Prepare research**. A known family reuses its scorer; **New problem — compile
Lean scorer** compiles the saved checked source without further model calls.
The seed is optional: known families supply a baseline, while the compiler
supplies a typed initial candidate that can be repaired if infeasible.
Review the signature and objective, or open **View compiler result**, then click
**Start research**. Compiler errors are shown with their failure stage.

Compilation requires local Lean/Lake and the dependencies in `problems/lean`
(override with `RESEARCH_LEAN_PROJECT`). Compiled scorers are stored beside the
SQLite database in `fitness/`; preserve both across restarts. Starting research
reloads and verifies the saved scorer without recompiling. Docker/image preflight
failures remain visible, and **Check evaluator availability** refreshes readiness.

Run history is stored in `runs/research.sqlite3` (override with `RESEARCH_STORE`).
Use a single backend worker. Download evidence from the engine page. For optional
shared authentication, set `RESEARCH_API_PASSWORD` and open `/api/health` to sign
in through the browser's authentication prompt; the default username is `research`.
