"""The frozen synthesis protocol: verdict parsing and the parse-only static gate.

No Docker, no model calls. The one `exec` here runs TEST-authored source to prove
the wrapper text behaves; it never executes model output.
"""

from fractions import Fraction

import pytest

from the_pigeon_holes.execution.signature_extractor import MetricGoal, OptimisationGoal
from the_pigeon_holes.fitness.base import CaseFitness
from the_pigeon_holes.fitness.synthesis.protocol import (
    WRAPPER_ENTRY,
    WRAPPER_SOURCE,
    Defect,
    metric_names,
    parse_verdict,
    static_gate,
)

GOAL = OptimisationGoal(MetricGoal("total_value", "maximize"), "sum")
TIED = OptimisationGoal(MetricGoal("total_value", "maximize"), "sum",
                        tie_breakers=(MetricGoal("slack", "minimize"),))

GOOD_SCORER = """
def validate(output, capacity):
    if not isinstance(output, list):
        return "return a list"
    return None

def score(output, capacity):
    return {"total_value": sum(output)}

def descriptor(output, capacity):
    return (float(len(output)),)
"""


def _run_wrapper(scorer_source, output, case_inputs):
    """Execute TEST-authored scorer source plus the host wrapper, in-process."""
    namespace = {}
    exec(compile(scorer_source + WRAPPER_SOURCE, "<test-scorer>", "exec"), namespace)
    return namespace[WRAPPER_ENTRY]({"output": output, "case_inputs": case_inputs})


def test_metric_names_includes_tie_breakers_in_order():
    assert metric_names(TIED) == ("total_value", "slack")


# --- wrapper behaviour -------------------------------------------------------

def test_wrapper_returns_exact_numerator_denominator_pairs():
    verdict = _run_wrapper(GOOD_SCORER, [1, 2, 3], {"capacity": 9})
    assert verdict["kind"] == "valid"
    assert verdict["metrics"] == {"total_value": ["6", "1"]}
    assert verdict["descriptor"] == ["3.0"]


def test_wrapper_reports_an_invalid_output_with_its_reason():
    verdict = _run_wrapper(GOOD_SCORER, "nope", {"capacity": 9})
    assert verdict == {"kind": "invalid", "reason": "return a list"}


def test_a_raising_validate_is_a_defect_not_an_invalid_candidate():
    """A broken scorer must never be reported as the candidate being invalid."""
    source = GOOD_SCORER.replace('    if not isinstance(output, list):\n        return "return a list"\n',
                                 "    raise KeyError('boom')\n")
    verdict = _run_wrapper(source, [1], {"capacity": 9})
    assert verdict["kind"] == "defect"
    assert verdict["where"] == "validate"
    assert verdict["type"] == "KeyError"


def test_float_metrics_are_rejected_as_inexact():
    source = GOOD_SCORER.replace('{"total_value": sum(output)}', '{"total_value": 1.5}')
    verdict = _run_wrapper(source, [1], {"capacity": 9})
    assert verdict["kind"] == "defect"
    assert verdict["where"] == "score"
    assert "float" in verdict["message"]


def test_fraction_metrics_survive_as_exact_pairs():
    source = GOOD_SCORER.replace(
        'def score(output, capacity):\n    return {"total_value": sum(output)}',
        'def score(output, capacity):\n'
        '    from fractions import Fraction\n'
        '    return {"total_value": Fraction(1, 3)}')
    verdict = _run_wrapper(source, [1], {"capacity": 9})
    assert verdict["metrics"] == {"total_value": ["1", "3"]}


def test_a_validate_returning_a_blank_reason_is_a_defect():
    source = GOOD_SCORER.replace('return "return a list"', 'return "   "')
    verdict = _run_wrapper(source, "nope", {"capacity": 9})
    assert verdict["kind"] == "defect"


def test_non_finite_descriptor_is_a_defect():
    source = GOOD_SCORER.replace("return (float(len(output)),)", 'return (float("inf"),)')
    verdict = _run_wrapper(source, [1], {"capacity": 9})
    assert verdict["kind"] == "defect"
    assert verdict["where"] == "descriptor"


def test_wrapper_definition_wins_over_a_scorer_of_the_same_name():
    source = GOOD_SCORER + f"\ndef {WRAPPER_ENTRY}(payload):\n    return 'hijacked'\n"
    assert _run_wrapper(source, [1, 2], {"capacity": 9})["kind"] == "valid"


# --- parse_verdict -----------------------------------------------------------

def test_parse_verdict_builds_an_exact_case_fitness():
    fitness = parse_verdict(
        {"kind": "valid", "metrics": {"total_value": ["7", "2"]}, "descriptor": ["1.5"]},
        GOAL, 1)
    assert isinstance(fitness, CaseFitness)
    assert fitness.valid and fitness.metrics == {"total_value": Fraction(7, 2)}
    assert fitness.behavioral_descriptor == (1.5,)


def test_parse_verdict_passes_an_invalid_verdict_through():
    fitness = parse_verdict({"kind": "invalid", "reason": "over capacity"}, GOAL, 1)
    assert isinstance(fitness, CaseFitness)
    assert not fitness.valid and fitness.failure_reason == "over capacity"


@pytest.mark.parametrize("payload, where", [
    ("not an object", "envelope"),
    ({"kind": "mystery"}, "envelope"),
    ({"kind": "invalid"}, "validate"),
    ({"kind": "invalid", "reason": "  "}, "validate"),
    ({"kind": "valid", "descriptor": ["1.0"]}, "score"),
    ({"kind": "valid", "metrics": {"wrong": ["1", "1"]}, "descriptor": ["1.0"]}, "score"),
    ({"kind": "valid", "metrics": {"total_value": ["1"]}, "descriptor": ["1.0"]}, "score"),
    ({"kind": "valid", "metrics": {"total_value": ["1", "0"]}, "descriptor": ["1.0"]}, "score"),
    ({"kind": "valid", "metrics": {"total_value": ["1", "1"]}, "descriptor": []}, "descriptor"),
    ({"kind": "valid", "metrics": {"total_value": ["1", "1"]}, "descriptor": ["a"]}, "descriptor"),
])
def test_every_malformed_verdict_is_a_defect(payload, where):
    result = parse_verdict(payload, GOAL, 1)
    assert isinstance(result, Defect) and result.where == where


def test_a_missing_tie_breaker_metric_is_a_defect():
    result = parse_verdict(
        {"kind": "valid", "metrics": {"total_value": ["1", "1"]}, "descriptor": ["0.0"]},
        TIED, 1)
    assert isinstance(result, Defect) and "slack" in result.message


def test_container_defect_is_carried_through():
    result = parse_verdict(
        {"kind": "defect", "where": "score", "type": "ZeroDivisionError", "message": "x"},
        GOAL, 1)
    assert result == Defect("score", "ZeroDivisionError", "x")


# --- static gate -------------------------------------------------------------

def test_static_gate_accepts_a_conforming_scorer():
    assert static_gate(GOOD_SCORER, declared_metrics=("total_value",), arity=1, goal=GOAL) == ()


@pytest.mark.parametrize("source, fragment", [
    (GOOD_SCORER.replace("def descriptor", "def unused"), "missing required function descriptor()"),
    ("import numpy\n" + GOOD_SCORER, "outside the allowed standard library"),
    ("from os import path\n" + GOOD_SCORER, "outside the allowed standard library"),
    (GOOD_SCORER + "\nprint('side effect')\n", "unexpected top-level"),
    (GOOD_SCORER.replace("sum(output)", "eval('1')"), "'eval' is not allowed"),
    (GOOD_SCORER + "\nx = ().__class__\n", "dunder"),
    ("def validate(:\n", "does not parse"),
])
def test_static_gate_rejects(source, fragment):
    problems = static_gate(source, declared_metrics=("total_value",), arity=1, goal=GOAL)
    assert any(fragment in problem for problem in problems), problems


def test_static_gate_rejects_declared_metrics_that_miss_the_goal():
    problems = static_gate(GOOD_SCORER, declared_metrics=("total_value",), arity=1, goal=TIED)
    assert any("do not match the optimisation goal" in problem for problem in problems)


def test_static_gate_rejects_a_zero_descriptor_arity():
    problems = static_gate(GOOD_SCORER, declared_metrics=("total_value",), arity=0, goal=GOAL)
    assert any("descriptor_arity" in problem for problem in problems)


def test_static_gate_does_not_execute_the_source():
    """A top-level side effect must be reported, never run."""
    hostile = "import math\nraise SystemExit('executed')\n" + GOOD_SCORER
    problems = static_gate(hostile, declared_metrics=("total_value",), arity=1, goal=GOAL)
    assert any("unexpected top-level" in problem for problem in problems)


def test_the_synthesis_package_never_executes_scorer_source_on_the_host():
    """Structural guarantee: synthesised code is data to the host, never code.

    Checks call syntax rather than substrings, so protocol.py may name the
    builtins it blocks without tripping its own rule.
    """
    import ast as ast_module
    from pathlib import Path

    package = Path(__file__).resolve().parents[1] / "src/the_pigeon_holes/fitness/synthesis"
    banned_calls = {"exec", "eval", "compile", "__import__"}
    banned_imports = {"importlib", "runpy", "pickle", "marshal"}
    for module in sorted(package.glob("*.py")):
        tree = ast_module.parse(module.read_text())
        for node in ast_module.walk(tree):
            if isinstance(node, ast_module.Call) and isinstance(node.func, ast_module.Name):
                assert node.func.id not in banned_calls, f"{module.name} calls {node.func.id}()"
            if isinstance(node, ast_module.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in banned_imports, \
                        f"{module.name} imports {alias.name}"
            if isinstance(node, ast_module.ImportFrom):
                assert (node.module or "").split(".")[0] not in banned_imports, \
                    f"{module.name} imports from {node.module}"
    # The gate inspects synthesised source only by parsing it.
    assert "ast.parse" in (package / "protocol.py").read_text()
