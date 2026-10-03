"""Local-only API for the real evolution loop with explicit demo ports.

Run: PYTHONPATH=src .venv/bin/python -m uvicorn the_pigeon_holes.ui.api:app --host 127.0.0.1 --port 8000
"""
import asyncio
import copy
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from .bridge import LabRun
from .formalization import FormalizationInput, prepare

runs: dict[str, LabRun] = {}


@asynccontextmanager
async def lifespan(app):
    yield
    tasks = [r.task for r in runs.values() if r.task and not r.task.done()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Research lab development bridge", lifespan=lifespan)


class StartInput(BaseModel):
    mode: str


def get_run(run_id):
    if run_id not in runs:
        raise HTTPException(404, "Run not found; development history resets when the server restarts.")
    return runs[run_id]


@app.get('/api/health')
def health():
    return {"mode": "python-demo", "engine": "EvolutionLoop", "generator": "demo", "evaluator": "analytic-demo"}


@app.post('/api/runs', status_code=201)
async def start_run(body: StartInput):
    if body.mode != 'demo':
        raise HTTPException(422, "Only the explicit demo is connected. Uploaded problems are not executed.")
    if any(r.task and not r.task.done() for r in runs.values()):
        raise HTTPException(409, "Stop the active local run before starting another.")
    if len(runs) >= 20:
        raise HTTPException(409, "Local history limit reached; restart the development API to clear it.")
    run = LabRun()
    runs[run.id] = run
    run.task = asyncio.create_task(run.run())
    return copy.deepcopy(run.snapshot['run'])


@app.get('/api/runs/{run_id}')
async def snapshot(run_id: str):
    return copy.deepcopy(get_run(run_id).snapshot)


@app.post('/api/runs/{run_id}/{action}')
async def control(run_id: str, action: str):
    run = get_run(run_id)
    if action not in ('pause', 'resume', 'stop'):
        raise HTTPException(404, 'Unknown command')
    getattr(run, action)()
    return {"status": run.snapshot['run']['status']}


@app.get('/api/runs/{run_id}/events')
async def events(run_id: str, request: Request, after: int = 0):
    run = get_run(run_id)
    try:
        cursor = max(after, int(request.headers.get('last-event-id', '0')))
    except ValueError:
        raise HTTPException(400, 'Invalid event cursor')
    if cursor < 0 or cursor > run.snapshot['sequence']:
        raise HTTPException(400, 'Cursor is outside this run; fetch a fresh snapshot')

    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            run.wake.clear()
            pending = [event for event in run.events if event['sequence'] > cursor]
            for event in pending:
                cursor = event['sequence']
                yield f"id: {cursor}\ndata: {json.dumps(event)}\n\n"
            try:
                await asyncio.wait_for(run.wake.wait(), timeout=15)
            except TimeoutError:
                yield ': heartbeat\n\n'

    return StreamingResponse(stream(), media_type='text/event-stream', headers={
        'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


formalization_lock = asyncio.Lock()

@app.post('/api/formalizations')
async def formalize_problem(body: FormalizationInput):
    if formalization_lock.locked():
        raise HTTPException(409, 'A formalization is already running. Try again when it completes.')
    async with formalization_lock:
        try:
            return await asyncio.wait_for(prepare(body), timeout=900)
        except TimeoutError:
            raise HTTPException(504, 'Formalization timed out. Please retry with a smaller problem.')
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Hosted formalization failed')
            raise HTTPException(503, 'Hosted Lean/Qwen service unavailable. Check backend Modal authentication and deployments.')


@app.get('/api/demo')
def demo_page():
    from pathlib import Path
    from fastapi.responses import FileResponse
    return FileResponse(Path(__file__).resolve().parents[3] / 'output' / 'idea-tree-demo.html')

from .attachments import router as attachment_router
app.include_router(attachment_router)


@app.get('/api/paper-theme.css')
def paper_theme():
    from pathlib import Path
    from fastapi.responses import FileResponse
    return FileResponse(Path(__file__).resolve().parents[3] / 'frontend/src/paper-theme.css', media_type='text/css')
