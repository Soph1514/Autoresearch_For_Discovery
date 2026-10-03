# Research lab frontend

The UI now uses the Python evolution backend through HTTP and SSE. It does not silently fall back to mock results when the API is unavailable.

From the repository root, start the API in terminal 1:

```sh
uv pip install --python .venv/bin/python 'fastapi>=0.115' 'uvicorn>=0.30'
PYTHONPATH=src .venv/bin/python -m uvicorn the_pigeon_holes.ui.api:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```sh
cd frontend
npm ci
npm run dev
```

Open the URL Vite prints (normally http://127.0.0.1:5173). Choose **Run routing demo**. The real evolution policy uses deterministic demo generation and analytic Pigou evaluation; no LLM credentials are needed. Add problem previews text/files locally only. Server history survives page refresh but not a backend restart.

- `contracts.ts`: frontend records and ordered event reducer.
- `http.ts`: API client, SSE reconnect, and command routing.
- `research.tsx`: snapshot loading, gap recovery, and run lifecycle.
- `mock.ts`: original standalone mock retained as an explicit test fixture; not selected at runtime.

Vite proxies `/api` to port 8000. Keep the API bound to localhost. See [integration status and remaining work](../docs/ui-integration-status.md) and [pipeline diagram](../docs/ui-pipeline.svg).

Auto overview gently zooms out as the graph grows. Manual pan/zoom overrides it. Candidate reveals are batched, opacity-only, and grouped by generation. Faded candidates remain inspectable. Reduced-motion preferences are respected.

```sh
npm test
npm run build
```
