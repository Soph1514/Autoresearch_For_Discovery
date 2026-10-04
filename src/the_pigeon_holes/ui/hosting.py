"""Static frontend and graceful deployment controls for the hosted singleton."""
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles


def configure_hosting(app, runs, volume, frontend):
    original_lifespan = app.router.lifespan_context
    state = {'draining': False, 'requests': 0}

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            yield
        await volume.commit.aio()

    app.router.lifespan_context = lifespan

    # Use ASGI middleware so a streaming request stays counted until its body ends.
    class DeploymentGate:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            tracked = (scope['type'] == 'http' and scope['method'] == 'POST'
                       and not scope['path'].startswith('/api/deployment'))
            control = (scope.get('path', '').startswith('/api/runs/')
                       and scope['path'].rsplit('/', 1)[-1] in ('pause', 'resume', 'stop'))
            if tracked and state['draining'] and not control:
                response = JSONResponse({'detail': 'An update is waiting. Please retry shortly.'},
                                        status_code=503, headers={'Retry-After': '30'})
                await response(scope, receive, send)
                return
            if tracked:
                state['requests'] += 1
            try:
                await self.app(scope, receive, send)
            finally:
                if tracked:
                    state['requests'] -= 1

    app.add_middleware(DeploymentGate)

    def authorize(request):
        expected = os.environ.get('RESEARCH_DEPLOY_TOKEN', '')
        if not expected or not secrets.compare_digest(
                request.headers.get('x-deploy-token', ''), expected):
            raise HTTPException(403, 'Deployment token required.')

    def status():
        return {**state, 'active_runs': sum(bool(r.task and not r.task.done()) for r in runs.values()),
                'revision': os.environ.get('RESEARCH_REVISION', 'unknown')}

    @app.get('/api/deployment')
    async def deployment_status(request: Request):
        authorize(request)
        return status()

    @app.post('/api/deployment/{action}')
    async def deployment_action(action: str, request: Request):
        authorize(request)
        if action == 'drain':
            state['draining'] = True
        elif action == 'resume':
            state['draining'] = False
        elif action == 'checkpoint':
            current = status()
            if not current['draining'] or current['requests'] or current['active_runs']:
                raise HTTPException(409, 'Wait for active work before checkpointing.')
            await volume.commit.aio()
        else:
            raise HTTPException(404, 'Unknown deployment action.')
        return status()

    app.mount('/', StaticFiles(directory=Path(frontend), html=True), name='frontend')
    return app
