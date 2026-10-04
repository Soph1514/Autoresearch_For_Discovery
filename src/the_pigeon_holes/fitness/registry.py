"""Server-controlled registry of fitness functions permitted for evolution runs."""

from __future__ import annotations

import hashlib
import importlib
import os
from pathlib import Path

from the_pigeon_holes.models.problem_contract import FitnessFunctionRef

from .base import FitnessFunction


def source_sha256(path: str | Path) -> str:
    """Hash the implementation source used by a built-in fitness function."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FitnessFunctionRegistry:
    """Contains only fitness functions explicitly trusted by the operator."""

    def __init__(self) -> None:
        self._functions: dict[tuple[str, str], FitnessFunction] = {}

    def register(self, fitness_function: FitnessFunction) -> None:
        reference = fitness_function.reference
        key = (reference.id, reference.version)
        if key in self._functions:
            raise ValueError(
                f"fitness function {reference.id!r} version {reference.version!r} is already registered"
            )
        self._functions[key] = fitness_function

    def resolve(self, reference: FitnessFunctionRef) -> FitnessFunction:
        key = (reference.id, reference.version)
        try:
            fitness_function = self._functions[key]
        except KeyError as exc:
            raise ValueError(
                f"fitness function {reference.id!r} version {reference.version!r} is not registered"
            ) from exc
        if fitness_function.reference.implementation_sha256 != reference.implementation_sha256:
            raise ValueError(
                f"fitness function {reference.id!r} implementation digest does not match the contract"
            )
        return fitness_function

    def find(self, identity: str, version: str) -> FitnessFunction:
        try:
            return self._functions[(identity, version)]
        except KeyError as exc:
            raise ValueError(
                f"fitness function {identity!r} version {version!r} is not registered"
            ) from exc

    def references(self) -> tuple[FitnessFunctionRef, ...]:
        return tuple(
            function.reference
            for _, function in sorted(self._functions.items())
        )


def builtin_registry() -> FitnessFunctionRegistry:
    from .autocorrelation import AutocorrelationFitnessFunction
    from .sidon_refinement import SidonRefinementFitness

    registry = FitnessFunctionRegistry()
    registry.register(AutocorrelationFitnessFunction())
    registry.register(SidonRefinementFitness())
    return registry


def configured_registry() -> FitnessFunctionRegistry:
    """Load an operator-owned registry, or use the built-in trusted registry."""
    target = os.environ.get("RESEARCH_FITNESS_REGISTRY")
    if not target:
        return builtin_registry()
    try:
        module_name, factory_name = target.split(":", 1)
    except ValueError as exc:
        raise RuntimeError(
            "RESEARCH_FITNESS_REGISTRY must have the form module:create_registry"
        ) from exc
    factory = getattr(importlib.import_module(module_name), factory_name)
    registry = factory()
    if not isinstance(registry, FitnessFunctionRegistry):
        raise TypeError("fitness registry factory must return FitnessFunctionRegistry")
    return registry
