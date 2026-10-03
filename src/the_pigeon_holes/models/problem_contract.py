"""Immutable, validated hand-off from formalization to evolutionary search."""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, TypeVar

from the_pigeon_holes.execution.interface_validation import (
    validate_case_inputs,
    validate_source_signature,
)
from the_pigeon_holes.execution.signature_extractor import (
    FUNCTION_NAME,
    ExtractedInterface,
    MetricGoal,
    OptimisationGoal,
    Parameter,
    extract_signature,
    verify_interface_syntax,
)

__all__ = [
    "EvaluationCase",
    "EvaluationSuite",
    "InterfaceDefinition",
    "MetricGoal",
    "OptimisationGoal",
    "Parameter",
    "ProblemContract",
    "ResourceLimits",
    "build_problem_contract",
    "validate_seed_program",
]

_Value = TypeVar("_Value")


class FrozenMapping(Mapping[Any, Any]):
    """Recursively immutable mapping used for run-bound benchmark data."""

    __slots__ = ("_values",)

    def __init__(self, values: Mapping[Any, Any]) -> None:
        object.__setattr__(self, "_values", MappingProxyType(dict(values)))

    def __setattr__(self, name: str, value: Any) -> None:
        raise TypeError("FrozenMapping is immutable")

    def __getitem__(self, key: Any) -> Any:
        return self._values[key]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return repr(self._values)

    def __deepcopy__(self, memo: dict[int, Any]) -> FrozenMapping:
        return self


@dataclass(frozen=True)
class FrozenList(Sequence[_Value]):
    """Immutable list representation that can later be materialized as a list."""

    values: tuple[_Value, ...]

    def __getitem__(self, index):
        return self.values[index]

    def __len__(self) -> int:
        return len(self.values)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return FrozenMapping({_freeze(key): _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return FrozenList(tuple(_freeze(item) for item in value))
    if type(value) is tuple:
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, FrozenMapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, FrozenList):
        return [_thaw(item) for item in value]
    if type(value) is tuple:
        return tuple(_thaw(item) for item in value)
    return value


@dataclass(frozen=True)
class InterfaceDefinition:
    """Complete versioned Python interface extracted from the Lean statement."""

    schema_version: str
    parameters: tuple[Parameter, ...]
    return_type: str
    solve_signature: str
    supporting_types_code: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", tuple(self.parameters))
        if not isinstance(self.schema_version, str) or not self.schema_version.strip():
            raise ValueError("interface schema_version cannot be empty")
        if not isinstance(self.return_type, str) or not isinstance(self.solve_signature, str):
            raise ValueError("interface return type and solve signature must be strings")
        if not isinstance(self.supporting_types_code, str):
            raise ValueError("supporting_types_code must be a string")
        if not all(isinstance(parameter, Parameter) for parameter in self.parameters):
            raise ValueError("interface parameters must be Parameter values")

    @classmethod
    def from_extracted(
        cls,
        interface: ExtractedInterface,
        *,
        schema_version: str = "python-interface-v1",
    ) -> InterfaceDefinition:
        return cls(
            schema_version=schema_version,
            parameters=tuple(interface.parameters),
            return_type=interface.return_type,
            solve_signature=interface.signature_str,
            supporting_types_code=interface.pydantic_classes_code,
        )


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    inputs: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("evaluation case id cannot be empty")
        if not isinstance(self.inputs, Mapping):
            raise ValueError("evaluation case inputs must be a mapping")
        object.__setattr__(self, "inputs", _freeze(self.inputs))

    def materialize_inputs(self) -> dict[str, Any]:
        """Return an isolated mutable copy suitable for sandbox invocation."""
        return _thaw(self.inputs)


@dataclass(frozen=True)
class EvaluationSuite:
    id: str
    cases: tuple[EvaluationCase, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "cases", tuple(self.cases))
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("evaluation suite id cannot be empty")
        if not self.cases:
            raise ValueError("evaluation suite must contain at least one case")
        if not all(isinstance(case, EvaluationCase) for case in self.cases):
            raise ValueError("evaluation suite cases must be EvaluationCase values")
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("evaluation case ids must be unique")


@dataclass(frozen=True)
class ResourceLimits:
    case_time_seconds: float
    candidate_time_seconds: float
    memory_mb: int
    max_iterations: int

    def __post_init__(self) -> None:
        numeric = (int, float)
        if (
            isinstance(self.case_time_seconds, bool)
            or not isinstance(self.case_time_seconds, numeric)
            or isinstance(self.candidate_time_seconds, bool)
            or not isinstance(self.candidate_time_seconds, numeric)
        ):
            raise ValueError("case and candidate time limits must be numeric")
        if self.case_time_seconds <= 0 or self.candidate_time_seconds <= 0:
            raise ValueError("case and candidate time limits must be positive")
        if not math.isfinite(self.case_time_seconds) or not math.isfinite(
            self.candidate_time_seconds
        ):
            raise ValueError("case and candidate time limits must be finite")
        if self.candidate_time_seconds < self.case_time_seconds:
            raise ValueError("candidate_time_seconds cannot be below case_time_seconds")
        if type(self.memory_mb) is not int or self.memory_mb <= 0:
            raise ValueError("memory_mb must be a positive integer")
        if type(self.max_iterations) is not int or self.max_iterations <= 0:
            raise ValueError("max_iterations must be a positive integer")


@dataclass(frozen=True)
class ProblemContract:
    natural_language_spec: str
    lean_specification: str
    interface: InterfaceDefinition
    seed_program: str
    evaluation_suite: EvaluationSuite
    optimisation_goal: OptimisationGoal
    resource_limits: ResourceLimits
    evaluator_version: str

    def __post_init__(self) -> None:
        for name in ("natural_language_spec", "lean_specification", "evaluator_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} cannot be empty")
        if not isinstance(self.interface, InterfaceDefinition):
            raise ValueError("interface must be an InterfaceDefinition")
        if not isinstance(self.evaluation_suite, EvaluationSuite):
            raise ValueError("evaluation_suite must be an EvaluationSuite")
        if not isinstance(self.optimisation_goal, OptimisationGoal):
            raise ValueError("optimisation_goal must be an OptimisationGoal")
        if not isinstance(self.resource_limits, ResourceLimits):
            raise ValueError("resource_limits must be ResourceLimits")
        _verify_contract_interface(self.interface, self.optimisation_goal)
        validate_seed_program(self.seed_program, self.interface.solve_signature)
        parameters = tuple(
            (parameter.name, parameter.python_type) for parameter in self.interface.parameters
        )
        for case in self.evaluation_suite.cases:
            try:
                validate_case_inputs(
                    case.materialize_inputs(),
                    parameters,
                    self.interface.supporting_types_code,
                )
            except ValueError as exc:
                raise ValueError(f"evaluation case {case.id!r}: {exc}") from exc

    @property
    def solve_signature(self) -> str:
        return self.interface.solve_signature


def _verify_contract_interface(
    interface: InterfaceDefinition,
    goal: OptimisationGoal,
) -> None:
    verify_interface_syntax(
        ExtractedInterface(
            function_name=FUNCTION_NAME,
            parameters=list(interface.parameters),
            return_type=interface.return_type,
            signature_str=interface.solve_signature,
            pydantic_classes_code=interface.supporting_types_code,
            optimisation_goal=goal,
        )
    )


def validate_seed_program(seed_program: str, solve_signature: str) -> None:
    """Raise ``ValueError`` unless the seed implements the exact interface."""
    error = validate_source_signature(seed_program, solve_signature)
    if error is not None:
        raise ValueError(f"seed_program {error}")


def build_problem_contract(
    *,
    natural_language_spec: str,
    lean_specification: str,
    seed_program: str,
    evaluation_suite_id: str,
    evaluation_cases: Mapping[str, Mapping[str, Any]],
    resource_limits: ResourceLimits,
    evaluator_version: str,
    model: str,
    client=None,
) -> ProblemContract:
    """Extract the interface and prepare an immutable, validated evaluation suite."""
    extracted = extract_signature(lean_specification, model=model, client=client)
    verify_interface_syntax(extracted)
    return ProblemContract(
        natural_language_spec=natural_language_spec,
        lean_specification=lean_specification,
        interface=InterfaceDefinition.from_extracted(extracted),
        seed_program=seed_program,
        evaluation_suite=EvaluationSuite(
            id=evaluation_suite_id,
            cases=tuple(
                EvaluationCase(id=case_id, inputs=inputs)
                for case_id, inputs in evaluation_cases.items()
            ),
        ),
        optimisation_goal=extracted.optimisation_goal,
        resource_limits=resource_limits,
        evaluator_version=evaluator_version,
    )
