"""Local-only API for the real evolution loop with explicit demo ports.

Run: PYTHONPATH=src .venv/bin/python -m uvicorn the_pigeon_holes.ui.api:app --host 127.0.0.1 --port 8000
"""
import asyncio
import anyio
import copy
import json
import os
from uuid import uuid4
from typing import Literal
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from .bridge import LabRun, now
from .formalization import FormalizationInput, prepare
from .contracts import InvalidControlTransition, TERMINAL_STATUSES

from .storage import ArtifactStore, contract_from_dict
from .preparation import ContractInput, prepare_contract, make_evaluator
from the_pigeon_holes.fitness.compiler import LeanFitnessError
from the_pigeon_holes.evolution.models import EvolutionConfig, EvolutionLimits
from the_pigeon_holes.llm import AnthropicGeneratorConfig, AnthropicProgramGenerator

store = ArtifactStore(os.environ.get('RESEARCH_STORE', 'runs/research.sqlite3'))
runs: dict[str, LabRun] = {}

async def prepare_and_save(body, progress=None):
    result = await prepare(body, progress=progress)
    identity = str(uuid4())
    result['formalization_id'] = identity
    store.put('formalization', identity, {'input': body.model_dump(), 'result': result})
    return result


@asynccontextmanager
async def lifespan(app):
    for artifact in store.all('run'):
        restored = LabRun.restore(artifact, store)
        runs[restored.id] = restored
    yield
    tasks = [r.task for r in runs.values() if r.task and not r.task.done()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Research lab development bridge", lifespan=lifespan)


@app.middleware('http')
async def optional_auth(request, call_next):
    # Leave localhost setup frictionless; a shared server may require HTTP Basic auth.
    password = os.environ.get('RESEARCH_API_PASSWORD')
    if password:
        import base64
        import secrets
        expected = os.environ.get('RESEARCH_API_USER', 'research') + ':' + password
        try:
            scheme, encoded = request.headers.get('authorization', '').split(' ', 1)
            supplied = base64.b64decode(encoded, validate=True).decode() if scheme.lower() == 'basic' else ''
        except (ValueError, UnicodeError):
            supplied = ''
        if not secrets.compare_digest(supplied.encode(), expected.encode()):
            return JSONResponse({'detail': 'Authentication required.'}, status_code=401,
                headers={'WWW-Authenticate': 'Basic realm="Research lab", charset="UTF-8"'})
    return await call_next(request)


class StartInput(BaseModel):
    mode: Literal['demo', 'custom']
    contract_id: str | None = None
    max_critic_calls: int = Field(default=0, ge=0, le=100)
    max_tokens: int = Field(default=5000000, gt=0, le=20000000)
    max_cost_usd: float = Field(default=50, gt=0, le=1000, allow_inf_nan=False)
    literature_review: bool = True
    reasoning_model: Literal['claude-opus-5-5', 'claude-opus-4-6', 'claude-sonnet-4-6'] = 'claude-opus-5-5'
    max_time_seconds: float = Field(default=300, gt=0, le=3600, allow_inf_nan=False)


def get_run(run_id):
    if run_id not in runs:
        raise HTTPException(404, "Run not found in this server history.")
    return runs[run_id]


@app.get('/api/health')
def health():
    return {'mode': 'research-bridge', 'engine': 'EvolutionLoop', 'demo_available': True,
            'custom_evaluator_configured': True}


@app.post('/api/runs', status_code=201)
async def start_run(body: StartInput):
    if any(r.task and not r.task.done() for r in runs.values()):
        raise HTTPException(409, "Stop the active local run before starting another.")
    if body.mode == 'custom':
        artifact = store.get('contract', body.contract_id or '')
        if artifact is None:
            raise HTTPException(422, 'Prepare a problem contract first.')
        model = body.reasoning_model
        try:
            contract = contract_from_dict(artifact['contract'])
            evaluator = await asyncio.to_thread(make_evaluator, contract, store=store)
            from the_pigeon_holes.llm.budget import ProviderTokenBudget
            budget = ProviderTokenBudget(body.max_tokens, max_cost_usd=body.max_cost_usd)
            generator = AnthropicProgramGenerator(AnthropicGeneratorConfig(
                model=model, reasoning_effort='high', max_output_tokens=12000,
                timeout_seconds=240, max_attempts=1, token_budget=body.max_tokens), budget=budget)
        except (RuntimeError, ImportError, AttributeError) as error:
            raise HTTPException(503, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        if any(r.task and not r.task.done() for r in runs.values()):
            await generator.aclose()
            raise HTTPException(409, 'Stop the active local run before starting another.')
        from the_pigeon_holes.llm.critic import AnthropicCritic, CriticConfig
        critic = AnthropicCritic(CriticConfig(model='claude-sonnet-4-6'), budget=generator.budget) if body.max_critic_calls else None
        run = LabRun(contract=contract, generator=generator, evaluator=evaluator, critic=critic,
            config=EvolutionConfig(), limits=EvolutionLimits(max_tokens=body.max_tokens, max_time_seconds=body.max_time_seconds, max_critic_calls=body.max_critic_calls),
            store=store, provenance=artifact['provenance'], literature_review=body.literature_review)
    else:
        run = LabRun(store=store)
    runs[run.id] = run
    run.task = asyncio.create_task(run.run())
    def finished(task):
        if task.cancelled() and run.snapshot['run']['status'] not in TERMINAL_STATUSES:
            run.cancel_pending('Run stopped before work began.')
            run.emit('run_status_changed', {'status': 'stopped', 'endedAt': now()})
    run.task.add_done_callback(finished)
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
            task = asyncio.create_task(prepare_and_save(body, progress=queue.put))
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
    task = asyncio.create_task(prepare_and_save(body))
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


@app.get('/api/capabilities')
def capabilities():
    ready, error = True, None
    from the_pigeon_holes.execution.container_runner import preflight
    from the_pigeon_holes.fitness.registry import configured_registry
    try:
        preflight()
    except RuntimeError as failure:
        ready, error = False, str(failure)
    try:
        references = configured_registry().references()
        fitness_functions = [
            {'id': reference.id, 'version': reference.version,
             'implementation_sha256': reference.implementation_sha256}
            for reference in references
        ]
    except (RuntimeError, ImportError, AttributeError, TypeError, ValueError) as failure:
        fitness_functions = []
        ready, error = False, str(failure)
    return {'custom_evaluator_configured': True,
            'evaluator_ready': ready, 'evaluator_error': error,
            'model_configured': bool(os.environ.get('RESEARCH_MODEL')), 'persistent_history': True,
            'evaluator_version': 'sandbox-fitness-v1',
            'fitness_functions': fitness_functions}


@app.get('/api/runs')
def history():
    return [copy.deepcopy(run.snapshot['run']) for run in runs.values()]


@app.get('/api/runs/{run_id}/artifact')
def run_artifact(run_id: str):
    get_run(run_id)
    return store.get('run', run_id)


@app.post('/api/contracts', status_code=201)
async def create_contract(body: ContractInput):
    artifact = store.get('formalization', body.formalization_id)
    try:
        contract = await prepare_contract(body, artifact, store=store)
    except LeanFitnessError as error:
        raise HTTPException(422, {'stage': error.stage, 'message': error.reason}) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error
    except Exception as error:
        import logging
        logging.getLogger(__name__).exception('Contract extraction failed')
        raise HTTPException(503, 'Interface extraction unavailable. Check the research model and backend credentials.') from error
    identity = str(uuid4())
    provenance = {'formalization_id': body.formalization_id, 'contract_id': identity,
        'check_artifact': artifact['result']['check_artifact'],
        'fidelity': artifact['result'].get('fidelity'), 'alignment_reviewed': body.alignment_reviewed}
    compiled = store.get('fitness', contract.fitness_function.id)
    compiler = None
    if compiled:
        compiler = {'status': 'compiled', 'fitness_id': contract.fitness_function.id,
                    'validation': compiled['manifest']['validation'], 'english_fidelity': 'not_proven'}
        provenance['compiler'] = compiler
    store.put('contract', identity, {'contract': contract, 'provenance': provenance})
    return {'id': identity, 'signature': contract.solve_signature, 'compiler': compiler,
        'metric': contract.optimisation_goal.primary.name,
        'direction': contract.optimisation_goal.primary.direction,
        'fitness_function': {'id': contract.fitness_function.id,
            'version': contract.fitness_function.version,
            'implementation_sha256': contract.fitness_function.implementation_sha256},
        'seed_status': ('evaluated at run start; infeasible seed can be repaired' if compiler else
                        'structurally_valid; behavioral evaluation required at run start')}


@app.get('/api/contracts/{identity}/compiler')
def compiled_evaluator(identity: str):
    artifact = store.get('contract', identity)
    if artifact is None or not artifact.get('provenance', {}).get('compiler'):
        raise HTTPException(404, 'No compiled evaluator for this contract.')
    saved = store.get('fitness', artifact['contract']['fitness_function']['id'])
    if saved is None:
        raise HTTPException(404, 'Compiled evaluator not found.')
    return saved['manifest']


@app.get('/api/formalizations/{identity}')
def saved_formalization(identity: str):
    artifact = store.get('formalization', identity)
    if artifact is None:
        raise HTTPException(404, 'Formalization not found.')
    return artifact


@app.get('/api/runs/{run_id}/numerical/{candidate_id}')
def numerical_evidence(run_id: str, candidate_id: str):
    record = get_run(run_id).evidence.get('numerical', {}).get(candidate_id)
    if record is None:
        raise HTTPException(404, 'No numerical witness recorded for this candidate.')
    return record


@app.get('/api/runs/{run_id}/summary')
def run_summary(run_id: str):
    run = get_run(run_id)
    from .storage import encode
    generation = encode(run.generation_config) or {}
    outcome = run.outcome or {}
    winner_id = (outcome.get('best_candidate') or {}).get('id') or next((
        e['ideaId'] for e in run.snapshot['elites'] if e['current'] and e['niche'] == 'Global best'), None)
    evaluation = encode(outcome.get('best_evaluation') or run.evidence.get('evaluations', {}).get(winner_id)) or {}
    return {'formalization_id': (run.provenance or {}).get('formalization_id'),
        'contract_id': (run.provenance or {}).get('contract_id'),
        'compiler': (run.provenance or {}).get('compiler'),
        'model': generation.get('model'), 'reported_tokens': outcome.get('tokens_used'),
        'generations': outcome.get('generations_completed'), 'stop_reason': outcome.get('stop_reason'),
        'active_seconds': outcome.get('elapsed_seconds'),
        'budget': run.budget_summary(), 'literature': run.literature,
        'best_candidate_id': winner_id, 'best_metrics': evaluation.get('metrics'),
        'scope': 'Reported evolution tokens exclude preparation and unknown in-flight billing.'}
