"""Real Lean tests: compilation, correspondence, scoring and pipeline selection."""

import asyncio
import json
import shutil
import subprocess
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from the_pigeon_holes.fitness import compiler
from the_pigeon_holes.models.problem_contract import EvaluationCase, MetricGoal, OptimisationGoal
from the_pigeon_holes.pipeline.runner import prepare_autoresearch

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "problems" / "lean"
MAX = """def feasible (capacity : Nat) (chosen : List Nat) : Prop := chosen.sum ≤ capacity
def objective (chosen : List Nat) : Nat := chosen.sum
def optimal (capacity : Nat) (chosen : List Nat) : Prop :=
  feasible capacity chosen ∧ ∀ other, feasible capacity other → objective other ≤ objective chosen
"""
MIN = """def optimum (floor : Int) : Prop :=
  ∃ chosen : Int, floor ≤ chosen ∧ ∀ other : Int, floor ≤ other → chosen ≤ other
"""


@pytest.fixture(scope="module")
def project():
    if not shutil.which("lake") or not (PROJECT / ".lake/packages/mathlib").exists():
        pytest.skip("local Lean/mathlib required")
    result = subprocess.run(["lake", "env", "lean", "--version"], cwd=PROJECT,
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        pytest.skip("pinned Lean toolchain unavailable")
    return PROJECT


def build(tmp_path, project, source=MAX, instance=None):
    return compiler.compile_fitness(statement="Optimize the construction.",
        instance=instance or {"capacity": 7}, lean_source=source,
        lean_project=project, artifacts=tmp_path)


@pytest.fixture(scope="module")
def maximum(tmp_path_factory, project):
    return build(tmp_path_factory.mktemp("maximum"), project,
                 "/-! Maximize a bounded list sum. -/\n" + MAX)


def test_trusted_scorer_precedes_formalization(tmp_path):
    def never(*args):
        pytest.fail("trusted scorer must not invoke formalization")
    prepared = prepare_autoresearch(problem_name="knapsack", statement="Knapsack",
        instance={"weights": [2, 4], "values": [3, 9], "capacity": 4},
        artifacts=tmp_path, lean_project=PROJECT, formalizer=never)
    assert not prepared.used_lean_fallback
    assert prepared.fitness.reference.id == "knapsack"
    result = prepared.fitness.evaluate_case(prepared.contract.evaluation_suite.cases[0], [1])
    assert result.valid and result.metrics["total_value"] == 9
    assert not list(tmp_path.iterdir())


def test_invalid_trusted_instance_does_not_fallback(tmp_path):
    with pytest.raises(ValueError, match="nonnegative"):
        prepare_autoresearch(problem_name="knapsack", statement="Knapsack",
            instance={"weights": [2], "values": [3], "capacity": -1},
            artifacts=tmp_path, lean_project=PROJECT, formalizer=lambda *_: pytest.fail("fallback"))


def test_missing_scorer_formalizes_once_then_no_llm(tmp_path, project):
    calls = []
    def formalize(statement, output):
        calls.append(statement)
        path = output / "Generated.lean"
        path.write_text(MAX)
        return path
    prepared = prepare_autoresearch(problem_name="new-list-budget", statement="Maximize sum within capacity.",
        instance={"capacity": 7}, artifacts=tmp_path, lean_project=project, formalizer=formalize)
    assert prepared.used_lean_fallback and len(calls) == 1
    assert prepared.registry.resolve(prepared.contract.fitness_function) is prepared.fitness
    case = prepared.contract.evaluation_suite.cases[0]
    first = prepared.fitness.evaluate_case(case, [3, 4])
    assert first == prepared.fitness.evaluate_case(case, [3, 4])
    assert first.valid and first.metrics == {"objective": 7}
    assert len(calls) == 1


def test_maximum_feasibility_and_strict_candidate_schema(maximum):
    case = maximum.contract().evaluation_suite.cases[0]
    assert maximum.direction == "maximize"
    good = maximum.evaluate_case(case, [2, 4])
    assert good.valid and good.metrics == {"objective": 6}
    assert good.evidence["kernel_checked"]
    for candidate in ([8], [-1], [True], "[4]", ["0); #eval IO.println 9"], (2, 3)):
        bad = maximum.evaluate_case(case, candidate)
        assert not bad.valid and not bad.metrics


@pytest.mark.parametrize("source", [MIN, """theorem optimum (floor : Int) :
  ∃ chosen : Int, floor ≤ chosen ∧ ∀ other : Int, floor ≤ other → chosen ≤ other :=
  ⟨floor, Int.le_refl floor, fun _other h => h⟩
"""])
def test_minimum_exists_signed_objective(tmp_path, project, source):
    minimum = build(tmp_path, project, source, {"floor": -5})
    case = minimum.contract().evaluation_suite.cases[0]
    assert minimum.direction == "minimize"
    assert minimum.evaluate_case(case, -4).metrics == {"objective": -4}
    assert not minimum.evaluate_case(case, -6).valid


@pytest.mark.parametrize("source,stage", [
    ("def broken : Nat := notARealIdentifier", "lean_compile_failed"),
    ("def broken := (", "lean_compile_failed"),
    ("def feasible (c : Nat) : Prop := c ≤ 7", "unsupported_formalization"),
    ("def optimum (c : Nat) : Prop := True ∧ ∀ y : Nat, True → y ≤ c + 1", "unsupported_formalization"),
    ("def optimum (c : Nat) : Prop := c ≤ 7 ∧ ∀ y : Nat, y ≤ 8 → y ≤ c", "unsupported_formalization"),
    ("def optimum (c : Nat) : Prop := True ∧ ∀ _y : Nat, True → 0 ≤ (0 : Nat)", "unsupported_formalization"),
    ("axiom cheat : False", "unsupported_formalization"),
    ("theorem cheat : False := by sorry", "unsupported_formalization"),
    ("#eval IO.println 7", "unsupported_formalization"),
    ("/-! Documentation is allowed, executable commands are not. -/\n#eval IO.println 7", "unsupported_formalization"),
    ("import Lean\ndef n := 1", "unsupported_formalization"),
    ("#exit\n#eval IO.println 7", "unsupported_formalization"),
    (MAX + MAX.replace("feasible", "feasible2").replace("objective", "objective2").replace("optimal", "optimal2"), "unsupported_formalization"),
])
def test_rejection_persists_failure(tmp_path, project, source, stage):
    with pytest.raises(compiler.LeanFitnessError) as error:
        build(tmp_path, project, source)
    assert error.value.stage == stage
    manifest = json.loads(next(tmp_path.glob("*/manifest.json")).read_text())
    assert manifest["status"] == "rejected" and manifest["failure_stage"] == stage
    assert manifest["lean_source"] == source


def test_compiler_disagreement_rejected(tmp_path, project, monkeypatch):
    original = compiler._compiled_fitness_source
    def corrupt(ir):
        return original(ir).replace(ir["objective"], "fun _ _ => 99")
    monkeypatch.setattr(compiler, "_compiled_fitness_source", corrupt)
    with pytest.raises(compiler.LeanFitnessError, match="evaluator_validation_failed"):
        build(tmp_path, project)


def test_runtime_disagreement_rejected(maximum, monkeypatch):
    original = compiler._run
    def corrupt(*args, **kwargs):
        result = original(*args, **kwargs)
        return result.replace('"SCORE:true:6"', '"SCORE:true:999"')
    monkeypatch.setattr(compiler, "_run", corrupt)
    result = maximum.evaluate_case(maximum.contract().evaluation_suite.cases[0], [2, 4])
    assert not result.valid and not result.metrics
    assert "evaluator_validation_failed" in result.failure_reason


def test_freeze_reload_and_contract_goal_binding(maximum):
    with pytest.raises(FrozenInstanceError):
        maximum.timeout = 999
    copy = maximum.manifest
    copy["representation"]["direction"] = "minimize"
    assert maximum.direction == "maximize"
    loaded = compiler.load_lean_fitness(maximum.artifact, maximum.reference)
    assert loaded.reference == maximum.reference
    assert loaded.timeout == maximum.timeout
    contract = maximum.contract()
    with pytest.raises(ValueError, match="frozen"):
        maximum.validate_contract(replace(contract,
            optimisation_goal=OptimisationGoal(MetricGoal("objective", "minimize"), "mean")))


def test_tampered_artifact_rejected(tmp_path, maximum):
    artifact = tmp_path / "copy"
    shutil.copytree(maximum.artifact, artifact)
    loaded = compiler.load_lean_fitness(artifact, maximum.reference)
    (artifact / "CompiledFitness.lean").write_text("-- tampered")
    result = loaded.evaluate_case(loaded.contract().evaluation_suite.cases[0], [2, 4])
    assert not result.valid and not result.metrics
    assert "changed" in result.failure_reason


def test_formalizer_failure_is_inspectable(tmp_path):
    def broken(*_):
        raise RuntimeError("provider unavailable")
    with pytest.raises(compiler.LeanFitnessError, match="formalization_failed"):
        compiler.formalize_and_compile(statement="Problem", instance={}, lean_project=PROJECT,
                              artifacts=tmp_path, formalizer=broken)
    failure = json.loads(next(tmp_path.glob("*/failure.json")).read_text())
    assert failure["stage"] == "formalization_failed"


def test_parallel_scoring_keeps_same_evaluator(maximum):
    async def run():
        case = maximum.contract().evaluation_suite.cases[0]
        return await asyncio.gather(*[
            asyncio.to_thread(maximum.evaluate_case, case, candidate)
            for candidate in ([2, 4], [7], [9])])
    reference = maximum.reference
    results = asyncio.run(run())
    assert [r.valid for r in results] == [True, True, False]
    assert maximum.reference == reference


def test_evolution_uses_frozen_lean_for_seed_and_offspring(maximum, monkeypatch):
    # Stub only the container boundary and generator. Scoring and evolution are real.
    from the_pigeon_holes.evaluation import production
    from the_pigeon_holes.evolution.loop import EvolutionLoop
    from the_pigeon_holes.evolution.models import (
        CandidateDraft, EvolutionConfig, EvolutionLimits, GenerationResult, TokenUsage,
    )
    from the_pigeon_holes.execution.container_runner import ContainerLimits, WorkerResult
    seen = []
    async def container(source, *args):
        seen.append(source)
        return WorkerResult(True, [7] if "return [capacity]" in source else [])
    monkeypatch.setattr(production, "run_candidate_async", container)
    class Generator:
        async def generate(self, requests):
            return [GenerationResult(r.id, TokenUsage(5, 5), CandidateDraft(
                hypothesis="Use the entire capacity.",
                source_code="def solve(capacity: int) -> list[int]:\n    return [capacity]\n",
                predicted_effect="Larger sum.", falsification_condition="Over capacity.",
                mechanism_tags=("direct",))) for r in requests]
    evaluator = production.SandboxCandidateEvaluator(maximum, ContainerLimits(256, 5), check_daemon=False)
    outcome = asyncio.run(EvolutionLoop(config=EvolutionConfig(
        min_islands=1, max_islands=1, offspring_per_island=1, max_batch_size=1,
        max_tokens_per_request=10), limits=EvolutionLimits(max_tokens=10),
        generator=Generator(), evaluator=evaluator).run(maximum.contract()))
    assert len(seen) == 2
    assert outcome.best_evaluation.metrics["objective"] == 7
    assert {record["fitness_function"]["implementation_sha256"]
            for record in evaluator.evidence.values()} == {maximum.reference.implementation_sha256}


def test_live_generated_subset_sum_fixture(tmp_path, project):
    problem = ROOT / "problems/subset_sum"
    scorer = compiler.compile_fitness(statement=(problem / "problem.txt").read_text(),
        instance=json.loads((problem / "instance.json").read_text()),
        lean_source=(problem / "Generated.lean").read_text(), lean_project=project,
        artifacts=tmp_path, provenance=json.loads((problem / "generation.json").read_text()))
    case = scorer.contract().evaluation_suite.cases[0]
    assert scorer.evaluate_case(case, [1, 1, 0]).metrics == {"objective": 7}
    for candidate in ([0, 1, 1], [1, 0], [2, 0, 0]):
        result = scorer.evaluate_case(case, candidate)
        assert not result.valid and not result.metrics
