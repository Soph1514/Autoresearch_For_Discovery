"""Host side of candidate execution: run one candidate in a locked-down container.

The host never executes candidate code. It starts a container from the pinned
worker image, sends the source and one case over stdin, and reads one JSON
result from stdout. Every failure maps to a stage the evolution loop can record.
"""

from __future__ import annotations

import asyncio
import math
import json
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

DEFAULT_IMAGE = "the-pigeon-holes/candidate-worker:v1"

# Upper bound on bytes read from the worker. Larger output is an invalid result.
MAX_OUTPUT_BYTES = 1_000_000


@dataclass(frozen=True)
class ContainerLimits:
    memory_mb: int
    timeout_seconds: float
    cpus: float = 1.0
    pids_limit: int = 64
    tmpfs_mb: int = 16

    def __post_init__(self):
        for name in ('memory_mb', 'pids_limit', 'tmpfs_mb'):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f'{name} must be a positive integer')
        for name in ('timeout_seconds', 'cpus'):
            value = getattr(self, name)
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be positive and finite')


@dataclass(frozen=True)
class WorkerResult:
    ok: bool
    output: Any = None
    failure_stage: str | None = None
    failure_reason: str | None = None


def preflight(image: str = DEFAULT_IMAGE) -> str:
    """Raise a RuntimeError with a diagnostic if the daemon or image is missing."""
    try:
        info = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=10,
        )
        if info.returncode != 0:
            raise RuntimeError("Docker daemon is not reachable. Start Docker Desktop and retry.")
        present = subprocess.run(
            ["docker", "image", "inspect", image, "--format", "{{.Id}}"], capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("Docker preflight failed. Check Docker installation and daemon availability.") from error
    if present.returncode != 0:
        raise RuntimeError(
            f"Worker image {image!r} is missing. Build it with "
            "`docker build -t the-pigeon-holes/candidate-worker:v1 docker/worker`."
        )

    return present.stdout.strip()


def run_arguments(name: str, limits: ContainerLimits, image: str) -> list[str]:
    """Return the `docker run` arguments that enforce the sandbox settings."""
    return [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        f"/tmp:rw,size={limits.tmpfs_mb}m,mode=1777",
        "--memory",
        f"{limits.memory_mb}m",
        "--memory-swap",
        f"{limits.memory_mb}m",
        "--cpus",
        str(limits.cpus),
        "--pids-limit",
        str(limits.pids_limit),
        "--user",
        "65534:65534",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        image,
    ]


class _OutputLimitExceeded(Exception):
    pass


async def _read_bounded(stream):
    chunks, total = [], 0
    while chunk := await stream.read(65536):
        total += len(chunk)
        if total > MAX_OUTPUT_BYTES:
            raise _OutputLimitExceeded()
        chunks.append(chunk)
    return b''.join(chunks)


async def _remove_container(name):
    process = await asyncio.create_subprocess_exec(
        'docker', 'rm', '--force', name,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, diagnostics = await asyncio.wait_for(process.communicate(), timeout=10)
        if process.returncode != 0 and b'No such container' not in diagnostics:
            raise RuntimeError(f'Could not confirm removal of container {name}; check Docker.')
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError(f'Could not confirm removal of container {name}; check Docker.')


async def run_candidate_async(
    source: str,
    entry_point: str,
    args: Mapping[str, Any],
    limits: ContainerLimits,
    image: str = DEFAULT_IMAGE,
) -> WorkerResult:
    """Run one isolated case; cancellation waits for named-container cleanup."""
    payload = json.dumps(
        {"source": source, "entry_point": entry_point, "args": dict(args)}, allow_nan=False,
    ).encode()
    name = f"candidate-{uuid.uuid4().hex}"
    launch = asyncio.create_task(asyncio.create_subprocess_exec(
        *run_arguments(name, limits, image), stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    ))
    try:
        process = await asyncio.shield(launch)
    except asyncio.CancelledError:
        process = await launch
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()
        await _remove_container(name)
        raise

    async def send():
        try:
            process.stdin.write(payload)
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            process.stdin.close()

    tasks = [asyncio.create_task(send()), asyncio.create_task(_read_bounded(process.stdout)),
             asyncio.create_task(_read_bounded(process.stderr)), asyncio.create_task(process.wait())]
    try:
        try:
            _, stdout, _, returncode = await asyncio.wait_for(
                asyncio.gather(*tasks), timeout=limits.timeout_seconds,
            )
        except TimeoutError:
            return WorkerResult(False, failure_stage='timeout', failure_reason='wall-clock limit')
        except _OutputLimitExceeded:
            return WorkerResult(False, failure_stage='invalid_output', failure_reason='output too large')
        if returncode == 137:
            return WorkerResult(False, failure_stage='memory', failure_reason='killed (exit 137)')
        if returncode != 0:
            return WorkerResult(False, failure_stage='crash', failure_reason=f'worker exited {returncode}')
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
        # Stop the client before removal so it cannot create the container later.
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()
        await asyncio.gather(*tasks, return_exceptions=True)
        cleanup = asyncio.create_task(_remove_container(name))
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await cleanup
            raise
