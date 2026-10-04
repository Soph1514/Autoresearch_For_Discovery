"""Stable version-one contracts shared by the local API and event bridge."""

from __future__ import annotations

from typing import Literal, TypedDict

SCHEMA_VERSION = 1

RunStatus = Literal[
    "running",
    "pausing",
    "paused",
    "stopping",
    "stopped",
    "completed",
    "failed",
]
ControlAction = Literal["pause", "resume", "stop"]

TERMINAL_STATUSES: frozenset[RunStatus] = frozenset(
    {"stopped", "completed", "failed"}
)
EVENT_TYPES = frozenset(
    {
        "idea_created",
        "experiment_updated",
        "elite_changed",
        "log_added",
        "generation_failed",
        "assessment_recorded",
        "run_status_changed",
    }
)


class ControlAcknowledgement(TypedDict):
    schemaVersion: Literal[1]
    runId: str
    action: ControlAction
    applied: bool
    status: RunStatus


class InvalidControlTransition(ValueError):
    """The requested control cannot be applied to the current run state."""

