"""Compile Lean specifications into frozen, deterministic fitness evaluators.

Only initialization can call a formalizer. The scorer holds no model/client.
See docs/fitness-compiler.md for the intentionally small accepted language.
"""

from __future__ import annotations

import hashlib
import json
import keyword
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping
from uuid import uuid4

from the_pigeon_holes.models.problem_contract import (
    EvaluationCase, EvaluationSuite, FitnessFunctionRef, InterfaceDefinition,
    MetricGoal, OptimisationGoal, Parameter, ProblemContract, ResourceLimits,
)

from .base import CaseFitness

COMPILER = Path(__file__).with_name("lean") / "Compiler.lean"
VERSION = "lean-fitness-v1"
TYPES = {"Nat": "int", "Int": "int", "List Nat": "list[int]", "List Int": "list[int]"}
MAX_INTEGER = 2**53 - 1  # The evolution engine aggregates metrics as doubles.


class LeanFitnessError(RuntimeError):
    def __init__(self, stage: str, reason: str, artifact: Path | None = None):
        self.stage, self.reason, self.artifact = stage, reason, artifact
        super().__init__(f"{stage}: {reason}" + (f"; artifacts: {artifact}" if artifact else ""))


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _implementation_hash() -> str:
    return _digest(Path(__file__).read_bytes() + COMPILER.read_bytes())


def _run(project: Path, workspace: Path, source: Path, *, timeout: float,
         stage: str, output: Path | None = None) -> str:
    env = os.environ.copy()
    env["LEAN_PATH"] = str(workspace)  # Lake prepends the pinned dependency paths.
    command = ["lake", "env", "lean", f"--root={workspace}", "-DmaxHeartbeats=2000000",
               "-DmaxRecDepth=4096", "-DElab.async=false"]
    if output is not None:
        command += ["-o", str(output)]
    command.append(str(source))
    try:
        result = subprocess.run(command, cwd=project, env=env, capture_output=True,
                                text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LeanFitnessError(stage, f"Lean execution failed: {exc}", workspace) from exc
    log = result.stdout + result.stderr
    if result.returncode:
        if "unsupported_formalization:" in log:
            stage = "unsupported_formalization"
        elif "lean_compile_failed:" in log:
            stage = "lean_compile_failed"
        raise LeanFitnessError(stage, log.strip(), workspace)
    return log


def _literal(value: object, schema: str) -> str:
    if schema.startswith("List "):
        if type(value) is not list or len(value) > 10000:
            raise ValueError("expected a list with at most 10000 elements")
        return "[" + ", ".join(_literal(v, schema[5:]) for v in value) + "]"
    if type(value) is not int or abs(value) > MAX_INTEGER:
        raise ValueError("expected an integer in the exact scoring range")
    if schema == "Nat" and value < 0:
        raise ValueError("Nat values cannot be negative")
    return f"({value} : {schema})"


def _compiled_fitness_source(ir: dict) -> str:
    params = ir["parameters"]
    # Canonical bound variable names avoid collisions with generated Lean names.
    binders = " ".join(f"(p{idx} : {p['type']})" for idx, p in enumerate(params))
    args = " ".join(f"p{idx}" for idx in range(len(params)))
    candidate = ir["candidate_type"]
    function_type = " → ".join([p["type"] for p in params] + [candidate])
    unfold = ", ".join(["frozenFitnessFeasible"] + ir["definitions"])
    f = f"frozenFitnessFeasible {args}"
    o = f"frozenFitnessObjective {args}"
    cmp = f"{o} other ≤ {o} chosen" if ir["direction"] == "maximize" else f"{o} chosen ≤ {o} other"
    relation = f"{f} chosen ∧ ∀ other : {candidate}, {f} other → {cmp}"
    quantifier = f"∀ {binders}, " if params else ""
    if ir["shape"] == "exists":
        rhs = f"∃ chosen : {candidate}, {relation}"
        if ir["kind"] == "theorem":
            equivalence = f"({ir['original']}) ↔ ({quantifier}{rhs})"
        else:
            equivalence = f"{quantifier}({ir['declaration']} {args}) ↔ ({rhs})"
    else:
        equivalence = f"∀ {binders} (chosen : {candidate}), ({ir['declaration']} {args} chosen) ↔ ({relation})"
    return (
        "import Specification\nset_option Elab.async false\n"
        f"def frozenFitnessFeasible : {function_type} → Prop := {ir['feasible']}\n"
        f"def frozenFitnessObjective : {function_type} → {ir['objective_type']} := {ir['objective']}\n"
        f"instance frozenFitnessDecision {binders} (c : {candidate}) : Decidable (frozenFitnessFeasible {args} c) := by\n"
        f"  dsimp only [{unfold}]\n  infer_instance\n"
        f"theorem frozen_fitness_correspondence : {equivalence} := "
        + ("Iff.rfl\n" if ir["kind"] == "theorem" else "by intros; exact Iff.rfl\n")
    )


@dataclass(frozen=True)
class LeanFitnessFunction:
    """Content-bound scorer. Candidate containers never receive its artifact path."""

    artifact: Path
    lean_project: Path
    reference: FitnessFunctionRef
    _manifest_text: str = field(repr=False)
    timeout: float = 30.0

    @property
    def manifest(self) -> dict:
        return json.loads(self._manifest_text)  # Return copies, never mutable internal state.

    @property
    def direction(self) -> str:
        return self.manifest["representation"]["direction"]

    def _integrity(self) -> None:
        manifest = self.manifest
        if (self.artifact / "manifest.json").read_text() != self._manifest_text:
            raise LeanFitnessError("evaluator_validation_failed", "frozen manifest changed", self.artifact)
        if _digest(self._manifest_text.encode()) != self.reference.implementation_sha256:
            raise LeanFitnessError("evaluator_validation_failed", "manifest digest mismatch", self.artifact)
        if self.reference.id != "lean-" + self.reference.implementation_sha256 or self.reference.version != VERSION:
            raise LeanFitnessError("evaluator_validation_failed", "evaluator reference mismatch", self.artifact)
        if self.timeout != manifest["timeout_seconds"]:
            raise LeanFitnessError("evaluator_validation_failed", "frozen timeout changed", self.artifact)
        if _implementation_hash() != manifest["implementation_sha256"]:
            raise LeanFitnessError("evaluator_validation_failed", "evaluator implementation changed", self.artifact)
        for name, digest in manifest["files"].items():
            if _digest((self.artifact / name).read_bytes()) != digest:
                raise LeanFitnessError("evaluator_validation_failed", f"frozen {name} changed", self.artifact)
        for name, digest in manifest["project_files"].items():
            if _digest((self.lean_project / name).read_bytes()) != digest:
                raise LeanFitnessError("evaluator_validation_failed", f"Lean dependency configuration {name} changed", self.artifact)

    def validate_contract(self, problem: ProblemContract) -> None:
        self._integrity()
        expected = self.interface()
        if (problem.fitness_function != self.reference or problem.interface != expected
                or problem.lean_specification != self.manifest["lean_source"]
                or problem.optimisation_goal != OptimisationGoal(MetricGoal("objective", self.direction), "mean")):
            raise ValueError("contract differs from the frozen Lean evaluator")
        for case in problem.evaluation_suite.cases:
            self._arguments(case.materialize_inputs())

    def interface(self) -> InterfaceDefinition:
        ir = self.manifest["representation"]
        parameters = tuple(Parameter(p["name"], TYPES[p["type"]]) for p in ir["parameters"])
        return_type = TYPES[ir["candidate_type"]]
        signature = "def solve(" + ", ".join(f"{p.name}: {p.python_type}" for p in parameters) + f") -> {return_type}:"
        return InterfaceDefinition("lean-fitness-v1", parameters, return_type, signature)

    def contract(self, *, seed_program: str | None = None,
                 limits: ResourceLimits | None = None) -> ProblemContract:
        manifest = self.manifest
        interface = self.interface()
        default = "[]" if interface.return_type.startswith("list") else "0"
        return ProblemContract(
            natural_language_spec=manifest["statement"], lean_specification=manifest["lean_source"],
            interface=interface, seed_program=seed_program or interface.solve_signature + f"\n    return {default}\n",
            evaluation_suite=EvaluationSuite("lean-instance", (EvaluationCase("instance", manifest["instance"]),)),
            optimisation_goal=OptimisationGoal(MetricGoal("objective", self.direction), "mean"),
            resource_limits=limits or ResourceLimits(5, 120, 256, 10), fitness_function=self.reference,
        )

    def _arguments(self, instance: Mapping[str, object]) -> str:
        params = self.manifest["representation"]["parameters"]
        if set(instance) != {p["name"] for p in params}:
            raise ValueError("instance keys must match Lean parameters: " + ", ".join(p["name"] for p in params))
        return " ".join(_literal(instance[p["name"]], p["type"]) for p in params)

    def evaluate_case(self, case: EvaluationCase, output: object) -> CaseFitness:
        try:
            self._integrity()
            args = self._arguments(case.materialize_inputs())
            ir = self.manifest["representation"]
            try:
                candidate = _literal(output, ir["candidate_type"])
            except ValueError as exc:
                return CaseFitness(False, failure_reason=f"invalid_candidate: {exc}")
            feasible = f"decide (frozenFitnessFeasible {args} {candidate})"
            objective = f"frozenFitnessObjective {args} {candidate}"
            with tempfile.TemporaryDirectory(prefix="lean-score-") as temporary:
                query = Path(temporary) / "Score.lean"
                # Emit a value only for feasible candidates. No model, no translated arithmetic.
                query.write_text("import CompiledFitness\n" +
                    f'#eval if {feasible} then "SCORE:true:" ++ toString ({objective}) else "SCORE:false"\n')
                log = _run(self.lean_project, self.artifact, query, timeout=self.timeout,
                           stage="evaluator_validation_failed")
                rows = [row.strip('"') for row in log.splitlines() if row.startswith('"SCORE:')]
                if len(rows) != 1:
                    raise LeanFitnessError("evaluator_validation_failed", "missing unique Lean score")
                valid = rows[0].startswith("SCORE:true:")
                value = int(rows[0].split(":")[-1]) if valid else None
                certificate = "import CompiledFitness\nset_option Elab.async false\n" + (
                    f"example : {feasible} = {'true' if valid else 'false'} := by decide\n")
                if valid:
                    if abs(value) > MAX_INTEGER:
                        raise LeanFitnessError("evaluator_validation_failed", "objective outside exact scoring range")
                    certificate += f"example : ({objective}) = ({value} : {ir['objective_type']}) := by decide\n"
                query.write_text(certificate)
                _run(self.lean_project, self.artifact, query, timeout=self.timeout,
                     stage="evaluator_validation_failed")
                self._integrity()
                evidence = {"lean_certificate_sha256": _digest(certificate.encode()),
                            "lean_certificate": certificate,
                            "fitness_sha256": self.reference.implementation_sha256,
                            "kernel_checked": True}
                return (CaseFitness(True, {"objective": value}, evidence=evidence) if valid else
                        CaseFitness(False, failure_reason="infeasible", evidence=evidence))
        except (LeanFitnessError, ValueError, OSError) as exc:
            return CaseFitness(False, failure_reason=str(exc))


def compile_fitness(*, statement: str, instance: Mapping[str, object],
                      lean_source: str, lean_project: Path, artifacts: Path,
                      provenance: Mapping[str, object] | None = None,
                      timeout: float = 60.0) -> LeanFitnessFunction:
    """Compile and verify a Lean evaluator, persist the outcome, and freeze its scorer."""
    project = lean_project.resolve()
    workspace = artifacts.resolve() / uuid4().hex
    workspace.mkdir(parents=True)
    manifest = {"version": VERSION, "statement": statement, "instance": dict(instance),
                "lean_source": lean_source, "formalizer": dict(provenance or {}),
                "timeout_seconds": timeout, "english_fidelity": "not_proven",
                "implementation_sha256": _implementation_hash()}
    (workspace / "Generated.lean").write_text(lean_source)
    try:
        (workspace / "Compiler.lean").write_bytes(COMPILER.read_bytes())
        _run(project, workspace, workspace / "Compiler.lean", timeout=timeout,
             stage="compiler_failed", output=workspace / "Compiler.olean")
        gate = workspace / "Gate.lean"
        gate.write_text('import Compiler\n#check_fitness_source ' +
                        json.dumps(str(workspace / "Generated.lean")) + "\n")
        _run(project, workspace, gate, timeout=timeout, stage="unsupported_formalization")
        source = "import Compiler\n" + lean_source + "\n"
        specification = workspace / "Specification.lean"
        specification.write_text(source)
        _run(project, workspace, specification, timeout=timeout, stage="lean_compile_failed",
             output=workspace / "Specification.olean")
        compilation = workspace / "Compile.lean"
        compilation.write_text(source + "\n#compile_fitness\n")
        log = _run(project, workspace, compilation, timeout=timeout, stage="compiler_failed")
        rows = [line.removeprefix("FITNESS_JSON:") for line in log.splitlines() if line.startswith("FITNESS_JSON:")]
        if len(rows) != 1:
            raise LeanFitnessError("compiler_failed", "missing unique compiler result", workspace)
        ir = json.loads(rows[0])
        for p in ir["parameters"]:
            if not p["name"].isidentifier() or keyword.iskeyword(p["name"]):
                raise LeanFitnessError("unsupported_formalization", f"parameter is not a Python identifier: {p['name']}", workspace)
        if len({p["name"] for p in ir["parameters"]}) != len(ir["parameters"]):
            raise LeanFitnessError("unsupported_formalization", "duplicate instance parameter names", workspace)
        manifest["representation"] = ir
        compiled_fitness = workspace / "CompiledFitness.lean"
        compiled_fitness.write_text(_compiled_fitness_source(ir))
        _run(project, workspace, compiled_fitness, timeout=timeout, stage="evaluator_validation_failed",
             output=workspace / "CompiledFitness.olean")
        # Synthesize decidability generically; a single sample is insufficient.
        binders = " ".join(f"(p{i} : {p['type']})" for i, p in enumerate(ir["parameters"]))
        args = " ".join(f"p{i}" for i in range(len(ir["parameters"])))
        executable = workspace / "Executable.lean"
        executable.write_text("import CompiledFitness\n" +
            f"def frozen_decidable {binders} (c : {ir['candidate_type']}) : Bool := decide (frozenFitnessFeasible {args} c)\n")
        _run(project, workspace, executable, timeout=timeout, stage="unsupported_formalization")
        version = subprocess.run(["lake", "env", "lean", "--version"], cwd=project,
                                 capture_output=True, text=True, check=True, timeout=timeout).stdout.strip()
        manifest.update(lean_version=version, lean_project=str(project),
                        toolchain=(project / "lean-toolchain").read_text(),
                        dependencies=json.loads((project / "lake-manifest.json").read_text()),
                        validation={"compiled": True, "kernel_correspondence": True,
                                    "per_score_kernel_check": True}, status="checking")
        manifest["project_files"] = {name: _digest((project / name).read_bytes()) for name in
                                     ("lean-toolchain", "lake-manifest.json", "lakefile.toml")}
        manifest["files"] = {p.name: _digest(p.read_bytes()) for p in workspace.iterdir() if p.is_file()}
        encoded = _json(manifest)
        (workspace / "manifest.json").write_text(encoded)
        digest = _digest(encoded.encode())
        scorer = LeanFitnessFunction(workspace, project, FitnessFunctionRef("lean-" + digest, VERSION, digest), encoded, timeout)
        scorer._arguments(instance)
        # Require at least one actual evaluation/certificate before admitting the evaluator.
        probe = [] if ir["candidate_type"].startswith("List") else 0
        result = scorer.evaluate_case(EvaluationCase("initialization", instance), probe)
        if not result.evidence.get("kernel_checked"):
            raise LeanFitnessError("evaluator_validation_failed", result.failure_reason or "probe failed", workspace)
        manifest["validation"]["probe"] = {"candidate": probe, "valid": result.valid,
            "metrics": dict(result.metrics), "certificate_sha256": result.evidence["lean_certificate_sha256"]}
        manifest["status"] = "accepted"
        encoded = _json(manifest)
        (workspace / "manifest.json").write_text(encoded)
        digest = _digest(encoded.encode())
        return LeanFitnessFunction(workspace, project,
            FitnessFunctionRef("lean-" + digest, VERSION, digest), encoded, timeout)
    except Exception as exc:
        error = exc if isinstance(exc, LeanFitnessError) else LeanFitnessError("compiler_failed", str(exc), workspace)
        manifest.update(status="rejected", failure_stage=error.stage, failure_reason=error.reason)
        (workspace / "manifest.json").write_text(_json(manifest))
        raise error from exc


def load_lean_fitness(artifact: Path, expected: FitnessFunctionRef) -> LeanFitnessFunction:
    """Reload only when the caller already holds the content-bound accepted reference."""
    encoded = (artifact / "manifest.json").read_text()
    manifest = json.loads(encoded)
    if manifest.get("status") != "accepted" or expected.version != VERSION:
        raise LeanFitnessError("evaluator_validation_failed", "artifact is not an accepted evaluator", artifact)
    scorer = LeanFitnessFunction(artifact.resolve(), Path(manifest["lean_project"]), expected, encoded,
                                 manifest["timeout_seconds"])
    scorer._integrity()
    return scorer


Formalizer = Callable[[str, Path], Path]


def lea_formalizer(statement: str, output: Path, *, lean_project: Path | None = None) -> Path:
    """Use the existing Lea CLI; no custom executable interface is requested."""
    from the_pigeon_holes.formalization.formalise import (
        DEFAULT_MODEL, ROOT, lea_root, load_dotenv, require_model_credentials,
    )
    from the_pigeon_holes.formalization.lea import formalize
    load_dotenv()
    model = os.environ.get("LEA_MODEL", DEFAULT_MODEL)
    require_model_credentials(model)
    return formalize(
        lea_root=lea_root(), statement=statement,
        lean_project=lean_project or ROOT / "problems" / "lean",
        output=output, model=model, max_turns=12, timeout=600,
        task="Write Generated.lean formalizing the general problem using ordinary mathematical "
             "definitions of feasibility and optimality, including the objective comparison. "
             "Do not claim to solve the optimization problem or prove existence. "
             "Do not use sorry, axioms, tactics, metaprogramming or IO.",
    )


def formalize_and_compile(*, statement: str, instance: Mapping[str, object], lean_project: Path,
                     artifacts: Path, formalizer: Formalizer = lea_formalizer) -> LeanFitnessFunction:
    generation = artifacts.resolve() / ("formalization-" + uuid4().hex)
    generation.mkdir(parents=True)
    (generation / "request.json").write_text(_json({"statement": statement, "instance": dict(instance)}))
    try:
        source = (formalizer(statement, generation, lean_project=lean_project)
                  if formalizer is lea_formalizer else formalizer(statement, generation))
        generated = source.read_text()
    except Exception as exc:
        (generation / "failure.json").write_text(_json({"stage": "formalization_failed", "reason": str(exc)}))
        raise LeanFitnessError("formalization_failed", str(exc), generation) from exc
    metadata = generation / "lea_run.json"
    return compile_fitness(statement=statement, instance=instance, lean_source=generated,
                             lean_project=lean_project, artifacts=artifacts,
                             provenance={"generation_directory": str(generation),
                                         "details": json.loads(metadata.read_text()) if metadata.exists() else {}})
