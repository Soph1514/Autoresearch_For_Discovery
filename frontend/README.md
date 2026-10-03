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
Flow and Dagre; backend snapshots and SSE drive its state. `mock.ts` is only a test
fixture. Auto overview yields to manual pan/zoom; faded candidates stay inspectable.

```sh
npm test
npm run build
```
