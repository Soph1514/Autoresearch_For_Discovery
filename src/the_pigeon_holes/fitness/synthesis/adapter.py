"""A FitnessFunction whose scoring logic is synthesised and therefore untrusted.

Shaped deliberately after `LeanFitnessFunction` in `..compiler`: a workspace
directory, a frozen manifest, a content-bound reference, and an `_integrity()`
check at the top of every scoring call. The difference is where the work happens
— the Lean scorer shells out to the Lean kernel, this one ships the module to the
candidate worker container.

The synthesised source is never imported, compiled or executed on the host. It is
read as bytes, concatenated with the host-authored wrapper, and written to a
container's stdin.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from the_pigeon_holes.execution.container_runner import (
    DEFAULT_IMAGE,
    ContainerLimits,
    run_candidate_async,
)
from the_pigeon_holes.execution.signature_extractor import (
    ExtractedInterface,
    MetricGoal,
    OptimisationGoal,
    Parameter,
)
from the_pigeon_holes.models.problem_contract import (
    EvaluationCase,
    EvaluationSuite,
    FitnessFunctionRef,
    InterfaceDefinition,
    ProblemContract,
    ResourceLimits,
)

from ..base import CaseFitness
from .protocol import (
    SYNTHESIS_VERSION,
    WRAPPER_ENTRY,
    WRAPPER_SOURCE,
    Defect,
    metric_names,
    parse_verdict,
)

EVIDENCE_TIER = "lean_checked_synthesised"
SCORER_FILENAME = "scorer.py"


class SynthesisedFitnessError(RuntimeError):
    def __init__(self, stage: str, reason: str, artifact: Path | None = None):
        self.stage, self.reason, self.artifact = stage, reason, artifact
        super().__init__(f"{stage}: {reason}" + (f"; artifacts: {artifact}" if artifact else ""))


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _implementation_hash() -> str:
    """Bind every frozen scorer to the adapter and wrapper that will run it."""
    protocol = Path(__file__).with_name("protocol.py")
    return _digest(Path(__file__).read_bytes() + protocol.read_bytes())


def _goal_to_json(goal: OptimisationGoal) -> dict:
    return {
        "primary": {"name": goal.primary.name, "direction": goal.primary.direction},
        "aggregation": goal.aggregation,
        "tie_breakers": [{"name": tie.name, "direction": tie.direction}
                         for tie in goal.tie_breakers],
    }


def _goal_from_json(raw: Mapping) -> OptimisationGoal:
    return OptimisationGoal(
        primary=MetricGoal(**raw["primary"]),
        aggregation=raw["aggregation"],
        tie_breakers=tuple(MetricGoal(**tie) for tie in raw.get("tie_breakers", [])),
    )


def _interface_to_json(interface: ExtractedInterface) -> dict:
    return {
        "function_name": interface.function_name,
        "parameters": [{"name": p.name, "python_type": p.python_type}
                       for p in interface.parameters],
        "return_type": interface.return_type,
        "signature_str": interface.signature_str,
        "pydantic_classes_code": interface.pydantic_classes_code,
        "optimisation_goal": _goal_to_json(interface.optimisation_goal),
    }


@dataclass(frozen=True)
class SynthesisedFitnessFunction:
    """Content-bound scorer. The container receives the module, never the artifact path."""

    artifact: Path
    reference: FitnessFunctionRef
    _manifest_text: str = field(repr=False)
    timeout: float = 30.0
    image: str = DEFAULT_IMAGE
    memory_mb: int = 256

    @property
    def manifest(self) -> dict:
        return json.loads(self._manifest_text)  # Return copies, never mutable internal state.

    @property
    def goal(self) -> OptimisationGoal:
        return _goal_from_json(self.manifest["interface"]["optimisation_goal"])

    @property
    def descriptor_arity(self) -> int:
        return int(self.manifest["descriptor_arity"])

    def _integrity(self) -> None:
        manifest = self.manifest
        if (self.artifact / "manifest.json").read_text() != self._manifest_text:
            raise SynthesisedFitnessError("integrity", "frozen manifest changed", self.artifact)
        if _digest(self._manifest_text.encode()) != self.reference.implementation_sha256:
            raise SynthesisedFitnessError("integrity", "manifest digest mismatch", self.artifact)
        if (self.reference.id != "synth-" + self.reference.implementation_sha256
                or self.reference.version != SYNTHESIS_VERSION):
            raise SynthesisedFitnessError("integrity", "scorer reference mismatch", self.artifact)
        if self.timeout != manifest["timeout_seconds"]:
            raise SynthesisedFitnessError("integrity", "frozen timeout changed", self.artifact)
        if _implementation_hash() != manifest["implementation_sha256"]:
            raise SynthesisedFitnessError("integrity", "adapter or wrapper changed", self.artifact)
        for name, digest in manifest["files"].items():
            if _digest((self.artifact / name).read_bytes()) != digest:
                raise SynthesisedFitnessError("integrity", f"frozen {name} changed", self.artifact)

    def interface(self) -> InterfaceDefinition:
        stored = self.manifest["interface"]
        return InterfaceDefinition(
            "python-interface-v1",
            tuple(Parameter(p["name"], p["python_type"]) for p in stored["parameters"]),
            stored["return_type"],
            stored["signature_str"],
            stored["pydantic_classes_code"],
        )

    def contract(self, *, evaluation_suite: EvaluationSuite, seed_program: str | None = None,
                 limits: ResourceLimits | None = None) -> ProblemContract:
        manifest = self.manifest
        interface = self.interface()
        default = "[]" if interface.return_type.startswith("list") else "0"
        return ProblemContract(
            natural_language_spec=manifest["statement"],
            lean_specification=manifest["lean_source"],
            interface=interface,
            seed_program=seed_program or interface.solve_signature + f"\n    return {default}\n",
            evaluation_suite=evaluation_suite,
            optimisation_goal=self.goal,
            resource_limits=limits or ResourceLimits(5, 120, self.memory_mb, 1),
            fitness_function=self.reference,
        )

    def validate_contract(self, problem: ProblemContract) -> None:
        self._integrity()
        manifest = self.manifest
        if problem.fitness_function != self.reference:
            raise ValueError("contract does not name this synthesised scorer")
        if problem.interface != self.interface():
            raise ValueError("contract interface differs from the reviewed interface")
        if problem.lean_specification != manifest["lean_source"]:
            raise ValueError("contract Lean statement differs from the reviewed statement")
        if problem.optimisation_goal != self.goal:
            raise ValueError("contract optimisation goal differs from the reviewed goal")
        expected = set(metric_names(self.goal))
        if set(manifest["metric_names"]) != expected:
            raise ValueError("frozen metric names do not match the optimisation goal")

    def _module_source(self) -> str:
        """Read the reviewed bytes from disk; never import or compile them."""
        return (self.artifact / SCORER_FILENAME).read_text() + WRAPPER_SOURCE

    def evaluate_case(self, case: EvaluationCase, output: object) -> CaseFitness:
        try:
            self._integrity()
        except (SynthesisedFitnessError, OSError) as error:
            return CaseFitness(False, failure_reason=str(error))
        payload = {"output": output, "case_inputs": case.materialize_inputs()}
        limits = ContainerLimits(memory_mb=self.memory_mb, timeout_seconds=self.timeout)
        try:
            result = _run_sync(run_candidate_async(
                self._module_source(), WRAPPER_ENTRY, {"payload": payload}, limits, self.image))
        except OSError as error:
            return CaseFitness(False, failure_reason=f"scorer container failed: {error}")
        if not result.ok:
            return CaseFitness(
                False,
                failure_reason=f"scorer {result.failure_stage}: {result.failure_reason}",
                evidence={"scorer_defect": True, "stage": result.failure_stage},
            )
        verdict = parse_verdict(result.output, self.goal, self.descriptor_arity)
        if isinstance(verdict, Defect):
            # A broken scorer is not an invalid candidate; say which it is.
            return CaseFitness(False, failure_reason=f"scorer defect in {verdict.describe()}",
                               evidence={"scorer_defect": True, "where": verdict.where})
        evidence = {
            "fitness_sha256": self.reference.implementation_sha256,
            "evidence_tier": EVIDENCE_TIER,
            "kernel_checked": False,
            "scorer_defect": False,
        }
        return CaseFitness(verdict.valid, metrics=verdict.metrics,
                           behavioral_descriptor=verdict.behavioral_descriptor,
                           failure_reason=verdict.failure_reason,
                           evidence={**dict(verdict.evidence), **evidence})


def _run_sync(coroutine):
    """Drive one container call from the worker thread the evaluator already provides.

    `FitnessFunction.evaluate_case` is synchronous and `SandboxCandidateEvaluator`
    calls it through `asyncio.to_thread`, so no loop is running here and
    `asyncio.run` is legal. Called from a thread that does have a loop, this says
    so plainly rather than surfacing as a mysterious scoring failure.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    coroutine.close()
    raise RuntimeError(
        "a synthesised scorer cannot be evaluated from a thread with a running event "
        "loop; call evaluate_case through asyncio.to_thread as the evaluator does"
    )


def freeze_scorer(*, source: str, statement: str, lean_source: str,
                  interface: ExtractedInterface, metric_names_declared: tuple[str, ...],
                  descriptor_arity: int, descriptor_axes: tuple[Mapping, ...],
                  artifacts: Path, probe_case: EvaluationCase, probe_output: object,
                  review: Mapping, rejected_source: str = "", timeout: float = 30.0,
                  image: str = DEFAULT_IMAGE,
                  memory_mb: int = 256) -> SynthesisedFitnessFunction:
    """Persist the reviewed scorer, probe it through a real container, then freeze it.

    The digest chain is scorer.py bytes -> manifest["files"] -> manifest.json bytes
    -> implementation_sha256 -> contract.fitness_function, so one edited byte fails
    both `_integrity()` and the registry's `resolve()`.
    """
    workspace = artifacts.resolve() / uuid4().hex
    workspace.mkdir(parents=True)
    manifest = {
        "version": SYNTHESIS_VERSION,
        "statement": statement,
        "lean_source": lean_source,
        "interface": _interface_to_json(interface),
        "metric_names": list(metric_names_declared),
        "descriptor_arity": descriptor_arity,
        "descriptor_axes": [dict(axis) for axis in descriptor_axes],
        "evidence_tier": EVIDENCE_TIER,
        "accepted_by_human": True,
        "review": dict(review),
        "timeout_seconds": timeout,
        "image": image,
        "memory_mb": memory_mb,
        "english_fidelity": "not_proven",
        "correctness": "not_proven",
        "implementation_sha256": _implementation_hash(),
    }
    try:
        (workspace / SCORER_FILENAME).write_text(source)
        if rejected_source:
            (workspace / "rejected.py").write_text(rejected_source)
        (workspace / "lean.lean").write_text(lean_source)
        (workspace / "review.json").write_text(_json(dict(review)))
        manifest["files"] = {path.name: _digest(path.read_bytes())
                             for path in sorted(workspace.iterdir()) if path.is_file()}
        manifest["status"] = "checking"
        encoded = _json(manifest)
        (workspace / "manifest.json").write_text(encoded)
        digest = _digest(encoded.encode())
        probe_scorer = SynthesisedFitnessFunction(
            workspace, FitnessFunctionRef("synth-" + digest, SYNTHESIS_VERSION, digest),
            encoded, timeout, image, memory_mb)

        # Require one real container evaluation before admitting the scorer.
        probe = probe_scorer.evaluate_case(probe_case, probe_output)
        if probe.evidence.get("scorer_defect", True):
            raise SynthesisedFitnessError(
                "probe_failed", probe.failure_reason or "the scorer produced no verdict", workspace)
        manifest["validation"] = {
            "probe_case": probe_case.id,
            "valid": probe.valid,
            "metrics": {name: f"{value.numerator}/{value.denominator}"
                        for name, value in probe.metrics.items()},
            "failure_reason": probe.failure_reason,
        }
        manifest["status"] = "accepted"
        encoded = _json(manifest)
        (workspace / "manifest.json").write_text(encoded)
        digest = _digest(encoded.encode())
        return SynthesisedFitnessFunction(
            workspace, FitnessFunctionRef("synth-" + digest, SYNTHESIS_VERSION, digest),
            encoded, timeout, image, memory_mb)
    except Exception as exc:
        error = exc if isinstance(exc, SynthesisedFitnessError) else SynthesisedFitnessError(
            "freeze_failed", str(exc), workspace)
        manifest.update(status="rejected", failure_stage=error.stage, failure_reason=error.reason)
        (workspace / "manifest.json").write_text(_json(manifest))
        raise error from exc


def load_synthesised_fitness(artifact: Path,
                             expected: FitnessFunctionRef) -> SynthesisedFitnessFunction:
    """Reload only when the caller already holds the content-bound accepted reference."""
    encoded = (artifact / "manifest.json").read_text()
    manifest = json.loads(encoded)
    if manifest.get("status") != "accepted" or expected.version != SYNTHESIS_VERSION:
        raise SynthesisedFitnessError("integrity", "artifact is not an accepted scorer", artifact)
    scorer = SynthesisedFitnessFunction(
        artifact.resolve(), expected, encoded, manifest["timeout_seconds"],
        manifest["image"], manifest["memory_mb"])
    scorer._integrity()
    return scorer
