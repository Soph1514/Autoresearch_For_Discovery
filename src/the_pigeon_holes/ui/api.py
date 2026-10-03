"""Local-only API for the real evolution loop with explicit demo ports.

Run: PYTHONPATH=src .venv/bin/python -m uvicorn the_pigeon_holes.ui.api:app --host 127.0.0.1 --port 8000
"""
import asyncio
import anyio
import copy
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from .bridge import LabRun
from .formalization import FormalizationInput, prepare
from .contracts import InvalidControlTransition, TERMINAL_STATUSES

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
    try:
        return run.control(action)
    except InvalidControlTransition as error:
        raise HTTPException(409, str(error)) from error


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
            if run.snapshot['run']['status'] in TERMINAL_STATUSES:
                return
            try:
                await asyncio.wait_for(run.wake.wait(), timeout=15)
            except TimeoutError:
                yield ': heartbeat\n\n'

    return StreamingResponse(stream(), media_type='text/event-stream', headers={
        'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


formalization_lock = asyncio.Lock()

@app.post('/api/formalizations')
async def formalize_problem(body: FormalizationInput, request: Request, stream: bool = False):
    if formalization_lock.locked():
        raise HTTPException(409, 'A formalization is already running. Stop it before starting another.')
    await formalization_lock.acquire()
    if stream:
        async def events():
            queue = asyncio.Queue()
            task = asyncio.create_task(prepare(body, progress=queue.put))
            try:
                while not task.done() or not queue.empty():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=1)
                        yield json.dumps({'type': 'progress', **event}) + '\n'
                    except TimeoutError:
                        yield json.dumps({'type': 'heartbeat'}) + '\n'
                yield json.dumps({'type': 'result', 'result': await task}) + '\n'
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Hosted formalization failed')
                yield json.dumps({'type': 'error', 'message': 'Hosted Lean/Qwen service unavailable. The latest source and diagnostics are preserved.'}) + '\n'
            finally:
                task.cancel()
                with anyio.CancelScope(shield=True):
                    try:
                        await asyncio.gather(task, return_exceptions=True)
                    finally:
                        formalization_lock.release()
        return StreamingResponse(events(), media_type='application/x-ndjson',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    task = asyncio.create_task(prepare(body))
    try:
        while not task.done():
            if await request.is_disconnected():
                task.cancel()
                raise HTTPException(499, 'Request cancelled.')
            await asyncio.wait({task}, timeout=0.5)
        return await task
    except HTTPException:
        raise
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Hosted formalization failed')
        raise HTTPException(503, 'Hosted Lean/Qwen service unavailable. Check backend Modal authentication and deployments.')
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        formalization_lock.release()


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
