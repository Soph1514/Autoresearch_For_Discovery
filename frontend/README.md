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

Set `RESEARCH_MODEL` and `ANTHROPIC_API_KEY` on the backend. The built-in evaluator supports autocorrelation. Build its worker with
`docker build -t the-pigeon-holes/candidate-worker:v1 docker/worker` from the
repository root. No factory environment variable is needed for this family;
see [setup and remaining work](../docs/pipeline-next-steps.md) for custom adapters. Redeploy the updated
`research/lean-fidelity/modal_checker.py` so successful checks include provenance.

After formalization, fill the seed, suite and evaluator fields and prepare the
contract. Review its extracted signature and objective before starting research.
The seed is evaluated first; a failed seed stops generation. Docker/image preflight failures are shown explicitly, and **Check evaluator availability** refreshes
readiness without repeating extraction.

Run history is stored in `runs/research.sqlite3` (override with `RESEARCH_STORE`).
Use a single backend worker. Download evidence from the engine page. For optional
shared authentication, set `RESEARCH_API_PASSWORD` and open `/api/health` to sign
in through the browser's authentication prompt; the default username is `research`.
