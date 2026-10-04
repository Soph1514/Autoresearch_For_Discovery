"""Trust-boundary tests for required, content-addressed fitness functions."""

from dataclasses import replace
from fractions import Fraction

import pytest

from the_pigeon_holes.fitness.autocorrelation import (
    AUTOCORRELATION_FITNESS_REF,
    AutocorrelationFitnessFunction,
)
from the_pigeon_holes.fitness.registry import FitnessFunctionRegistry, builtin_registry
from the_pigeon_holes.evaluation.production import _aggregate
from the_pigeon_holes.execution.signature_extractor import MetricGoal
from the_pigeon_holes.models.problem_contract import FitnessFunctionRef
from the_pigeon_holes.problems.autocorrelation import autocorrelation_contract


def test_builtin_registry_resolves_exact_content_addressed_reference():
    fitness = builtin_registry().resolve(AUTOCORRELATION_FITNESS_REF)
    assert isinstance(fitness, AutocorrelationFitnessFunction)


def test_registry_fails_closed_for_unknown_or_changed_implementation():
    registry = builtin_registry()
    with pytest.raises(ValueError, match="not registered"):
        registry.resolve(FitnessFunctionRef("missing", "v1", "0" * 64))
    changed = replace(AUTOCORRELATION_FITNESS_REF, implementation_sha256="0" * 64)
    with pytest.raises(ValueError, match="digest does not match"):
        registry.resolve(changed)


def test_registry_rejects_duplicate_identity_and_version():
    registry = FitnessFunctionRegistry()
    registry.register(AutocorrelationFitnessFunction())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(AutocorrelationFitnessFunction())


def test_fitness_function_validates_contract_and_expected_output_length():
    fitness = AutocorrelationFitnessFunction()
    contract = autocorrelation_contract(8)
    fitness.validate_contract(contract)
    case = contract.evaluation_suite.cases[0]
    result = fitness.evaluate_case(case, [2**40] * 7)
    assert not result.valid
    assert result.failure_reason == "expected length 8, got 7"


@pytest.mark.parametrize(
    ("aggregation", "direction", "expected"),
    [
        ("sum", "maximize", Fraction(6)),
        ("mean", "maximize", Fraction(2)),
        ("median", "maximize", Fraction(2)),
        ("worst_case", "maximize", Fraction(1)),
        ("worst_case", "minimize", Fraction(3)),
    ],
)
def test_generic_aggregation_respects_goal_direction(
    aggregation, direction, expected
):
    assert _aggregate(
        [Fraction(1), Fraction(2), Fraction(3)],
        aggregation,
        MetricGoal("score", direction),
    ) == expected
