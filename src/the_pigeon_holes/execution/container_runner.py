"""Host side of candidate execution: run one candidate in a locked-down container.

The host never executes candidate code. It starts a container from the pinned
worker image, sends the source and one case over stdin, and reads one JSON
result from stdout. Every failure maps to a stage the evolution loop can record.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

DEFAULT_IMAGE = "the-pigeon-holes/candidate-worker:v1"

# Upper bound on bytes read from the worker. Larger output is an invalid result.
MAX_OUTPUT_BYTES = 1_000_000

# Seconds added to the wall-clock limit so the worker can finish its own report.
_GRACE_SECONDS = 2.0


@dataclass(frozen=True)
class ContainerLimits:
    memory_mb: int
    timeout_seconds: float
    cpus: float = 1.0
    pids_limit: int = 64
    tmpfs_mb: int = 16


@dataclass(frozen=True)
class WorkerResult:
    ok: bool
    output: Any = None
    failure_stage: str | None = None
    failure_reason: str | None = None


def preflight(image: str = DEFAULT_IMAGE) -> None:
    """Raise a RuntimeError with a diagnostic if the daemon or image is missing."""
    info = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        capture_output=True,
        text=True,
    )
    if info.returncode != 0:
        raise RuntimeError(
            "Docker daemon is not reachable. Start Docker Desktop and retry. "
            f"Detail: {info.stderr.strip()[:200]}"
        )
    present = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        text=True,
    )
    if present.returncode != 0:
        raise RuntimeError(
            f"Worker image {image!r} is missing. Build it with "
            "`docker build -t the-pigeon-holes/candidate-worker:v1 docker/worker`."
        )


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


def run_candidate(
    source: str,
    entry_point: str,
    args: Mapping[str, Any],
    limits: ContainerLimits,
    image: str = DEFAULT_IMAGE,
) -> WorkerResult:
    """Run `entry_point(**args)` from `source` in a fresh container."""
    payload = json.dumps(
        {"source": source, "entry_point": entry_point, "args": dict(args)},
        allow_nan=False,
    )
    name = f"candidate-{uuid.uuid4().hex}"
    command = run_arguments(name, limits, image)
    try:
        completed = subprocess.run(
            command,
            input=payload,
            capture_output=True,
            text=True,
            timeout=limits.timeout_seconds + _GRACE_SECONDS,
        )
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", name], capture_output=True)
        return WorkerResult(False, failure_stage="timeout", failure_reason="wall-clock limit")

    if len(completed.stdout.encode()) > MAX_OUTPUT_BYTES:
        return WorkerResult(False, failure_stage="invalid_output", failure_reason="output too large")
    if completed.returncode == 137:
        # SIGKILL from the memory cgroup, or an external kill. Treated as memory.
        return WorkerResult(False, failure_stage="memory", failure_reason="killed (exit 137)")
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return WorkerResult(
            False,
            failure_stage="crash",
            failure_reason=f"no JSON result (exit {completed.returncode})",
        )
    if not isinstance(report, dict) or report.get("status") not in ("ok", "error"):
        return WorkerResult(False, failure_stage="invalid_output", failure_reason="bad envelope")
    if report["status"] == "error":
        return WorkerResult(
            False,
            failure_stage="crash",
            failure_reason=f"{report.get('type')}: {report.get('message')}",
        )
    return WorkerResult(True, output=report.get("output"))
