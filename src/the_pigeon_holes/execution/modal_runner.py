"""One credential-free, network-blocked Modal Sandbox per candidate case."""
import asyncio
import json
import math

from .container_runner import MAX_OUTPUT_BYTES, WorkerResult

_app = None
_image = None


def configure(app, image):
    global _app, _image
    _app, _image = app, image


def preflight():
    if _app is None or _image is None:
        raise RuntimeError('Modal candidate runtime has not been configured.')
    return _image.object_id


async def _read_bounded(stream):
    chunks, total = [], 0
    async for chunk in stream:
        encoded = chunk.encode() if isinstance(chunk, str) else chunk
        total += len(encoded)
        if total > MAX_OUTPUT_BYTES:
            raise ValueError('output too large')
        chunks.append(encoded)
    return b''.join(chunks)


async def run_candidate(source, entry_point, args, limits):
    import modal
    preflight()
    payload = json.dumps({'source': source, 'entry_point': entry_point,
                          'args': dict(args)}, allow_nan=False).encode()
    # Modal has a finite sandbox lifetime even when local execution is unbounded.
    lifetime = min(86400, math.ceil(limits.timeout_seconds or 86400) + 60)
    launch = asyncio.create_task(modal.Sandbox.create.aio(
        'python', '-I', '/opt/worker/worker.py', app=_app, image=_image,
        timeout=lifetime, cpu=(limits.cpus, limits.cpus),
        memory=(limits.memory_mb, limits.memory_mb), block_network=True,
    ))
    try:
        sandbox = await asyncio.shield(launch)
    except asyncio.CancelledError:
        sandbox = await launch
        await sandbox.terminate.aio()
        raise
    tasks = []
    try:
        sandbox.stdin.write(payload)
        sandbox.stdin.write_eof()
        await sandbox.stdin.drain.aio()
        tasks = [asyncio.create_task(_read_bounded(sandbox.stdout)),
                 asyncio.create_task(_read_bounded(sandbox.stderr)),
                 asyncio.create_task(sandbox.wait.aio())]
        try:
            stdout, _, _ = await asyncio.wait_for(asyncio.gather(*tasks),
                                                  timeout=limits.timeout_seconds)
        except TimeoutError:
            return WorkerResult(False, failure_stage='timeout', failure_reason='wall-clock limit')
        except ValueError:
            return WorkerResult(False, failure_stage='invalid_output', failure_reason='output too large')
        if sandbox.returncode != 0:
            return WorkerResult(False, failure_stage='memory' if sandbox.returncode == 137 else 'crash',
                                failure_reason=f'worker exited {sandbox.returncode}')
        try:
            report = json.loads(stdout)
        except (ValueError, UnicodeError):
            return WorkerResult(False, failure_stage='crash', failure_reason='no JSON result')
        if not isinstance(report, dict) or report.get('status') not in ('ok', 'error'):
            return WorkerResult(False, failure_stage='invalid_output', failure_reason='bad envelope')
        if report['status'] == 'error':
            return WorkerResult(False, failure_stage='crash',
                                failure_reason=f"{report.get('type')}: {report.get('message')}")
        return WorkerResult(True, output=report.get('output'))
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        cleanup = asyncio.create_task(sandbox.terminate.aio())
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await cleanup
            raise
