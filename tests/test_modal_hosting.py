import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from the_pigeon_holes.execution import modal_runner
from the_pigeon_holes.execution.container_runner import ContainerLimits
from the_pigeon_holes.ui.hosting import configure_hosting


def test_deployment_drain_requires_token_and_preserves_controls(tmp_path, monkeypatch):
    monkeypatch.setenv('RESEARCH_DEPLOY_TOKEN', 'test-token')
    (tmp_path / 'index.html').write_text('<html>lab</html>')
    commits = []

    async def commit():
        commits.append(True)

    app = FastAPI()

    @app.post('/api/runs')
    async def start():
        return {'started': True}

    @app.post('/api/runs/a/stop')
    async def stop():
        return {'stopped': True}

    runs = {'a': SimpleNamespace(task=SimpleNamespace(done=lambda: False))}
    configure_hosting(app, runs, SimpleNamespace(commit=SimpleNamespace(aio=commit)), tmp_path)
    headers = {'X-Deploy-Token': 'test-token'}
    with TestClient(app) as client:
        assert client.get('/').status_code == 200
        assert client.post('/api/deployment/drain').status_code == 403
        assert client.post('/api/runs').status_code == 200
        assert client.post('/api/deployment/drain', headers=headers).status_code == 200
        assert client.post('/api/runs').status_code == 503
        assert client.post('/api/runs/a/stop').status_code == 200
        assert client.post('/api/deployment/checkpoint', headers=headers).status_code == 409
        runs.clear()
        assert client.post('/api/deployment/checkpoint', headers=headers).status_code == 200
        assert len(commits) == 1
        assert client.post('/api/deployment/resume', headers=headers).status_code == 200
        assert client.post('/api/runs').status_code == 200
    assert len(commits) == 2


class Stream:
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


def fake_sandbox(monkeypatch, output, *, wait_forever=False):
    import modal
    calls = []
    terminated = []

    async def drain():
        pass

    async def wait():
        if wait_forever:
            await asyncio.Event().wait()

    async def terminate():
        terminated.append(True)

    sandbox = SimpleNamespace(
        stdin=SimpleNamespace(write=lambda _: None, write_eof=lambda: None,
                              drain=SimpleNamespace(aio=drain)),
        stdout=Stream(output), stderr=Stream([]), wait=SimpleNamespace(aio=wait),
        terminate=SimpleNamespace(aio=terminate), returncode=0)

    async def create(*args, **kwargs):
        calls.append((args, kwargs))
        return sandbox

    monkeypatch.setattr(modal, 'Sandbox', SimpleNamespace(create=SimpleNamespace(aio=create)))
    monkeypatch.setattr(modal_runner, '_app', object())
    monkeypatch.setattr(modal_runner, '_image', SimpleNamespace(object_id='im-test'))
    return calls, terminated


def test_modal_worker_is_isolated_and_result_is_decoded(monkeypatch):
    calls, terminated = fake_sandbox(monkeypatch, ['{"status":"ok","output":42}'])
    result = asyncio.run(modal_runner.run_candidate('def solve(): return 42', 'solve', {},
                                                   ContainerLimits(128, 5)))
    assert result.ok and result.output == 42
    kwargs = calls[0][1]
    assert kwargs['block_network'] is True
    assert kwargs['memory'] == (128, 128)
    assert kwargs['cpu'] == (1, 1)
    assert 'secrets' not in kwargs and 'volumes' not in kwargs
    assert terminated == [True]


@pytest.mark.parametrize('output,stage', [(['not json'], 'crash'),
                                        (['[]'], 'invalid_output'),
                                        (['x' * 1_000_001], 'invalid_output')])
def test_modal_worker_rejects_bad_output_and_cleans_up(monkeypatch, output, stage):
    _, terminated = fake_sandbox(monkeypatch, output)
    result = asyncio.run(modal_runner.run_candidate('', 'solve', {}, ContainerLimits(128, 5)))
    assert not result.ok and result.failure_stage == stage
    assert terminated == [True]


def test_modal_worker_timeout_terminates_sandbox(monkeypatch):
    _, terminated = fake_sandbox(monkeypatch, [], wait_forever=True)
    result = asyncio.run(modal_runner.run_candidate('', 'solve', {}, ContainerLimits(128, .01)))
    assert result.failure_stage == 'timeout'
    assert terminated == [True]


def test_modal_worker_cancellation_terminates_sandbox(monkeypatch):
    calls, terminated = fake_sandbox(monkeypatch, [], wait_forever=True)

    async def scenario():
        task = asyncio.create_task(modal_runner.run_candidate('', 'solve', {}, ContainerLimits(128, 5)))
        while not calls:
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert terminated == [True]
