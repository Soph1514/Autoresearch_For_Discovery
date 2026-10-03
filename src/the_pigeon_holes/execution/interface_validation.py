"""Safe structural validation for extracted Python interfaces and inputs."""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


def validate_source_signature(source_code: str, required_signature: str) -> str | None:
    """Return an error when source is invalid or misses the exact ``solve`` signature."""
    try:
        source_tree = ast.parse(source_code)
    except SyntaxError as exc:
        return f"source is not valid Python: {exc}"
    solve_functions = [
        node
        for node in source_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "solve"
    ]
    if len(solve_functions) != 1:
        return "source must define exactly one top-level solve function"
    if isinstance(solve_functions[0], ast.AsyncFunctionDef):
        return "solve must be a synchronous function"
    try:
        required_tree = ast.parse(required_signature + "\n    ...")
    except SyntaxError as exc:
        raise ValueError(f"ProblemContract has an invalid solve_signature: {exc}") from exc
    required_function = required_tree.body[0]
    if not isinstance(required_function, ast.FunctionDef):
        raise ValueError("ProblemContract solve_signature must be a function definition")
    actual = solve_functions[0]
    if ast.dump(actual.args, include_attributes=False) != ast.dump(
        required_function.args, include_attributes=False
    ) or ast.dump(actual.returns, include_attributes=False) != ast.dump(
        required_function.returns, include_attributes=False
    ):
        return "solve signature does not match ProblemContract.solve_signature"
    return None


@dataclass(frozen=True)
class _ModelField:
    annotation: ast.expr
    required: bool


def validate_case_inputs(
    inputs: Mapping[str, Any],
    parameters: Sequence[tuple[str, str]],
    supporting_types_code: str,
) -> None:
    """Validate one case against type annotations without executing extracted code."""
    if not all(isinstance(name, str) for name in inputs):
        raise ValueError("case parameter names must be strings")
    expected_names = [name for name, _ in parameters]
    if sorted(inputs) != sorted(expected_names):
        raise ValueError(
            f"case keys {sorted(inputs)} do not match signature parameters "
            f"{sorted(expected_names)}"
        )
    models = _extract_model_fields(supporting_types_code)
    for name, type_string in parameters:
        try:
            annotation = ast.parse(type_string, mode="eval").body
        except SyntaxError as exc:
            raise ValueError(f"invalid type annotation for parameter {name!r}: {exc}") from exc
        _validate_value(inputs[name], annotation, f"inputs.{name}", models)


def _extract_model_fields(code: str) -> dict[str, dict[str, _ModelField]]:
    if not code.strip():
        return {}
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"supporting type definitions are not valid Python: {exc}") from exc
    models: dict[str, dict[str, _ModelField]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(isinstance(base, ast.Name) and base.id == "BaseModel" for base in node.bases):
            continue
        if node.name in models:
            raise ValueError(f"supporting type {node.name!r} is defined more than once")
        fields: dict[str, _ModelField] = {}
        for statement in node.body:
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                if statement.target.id in fields:
                    raise ValueError(
                        f"supporting type {node.name!r} repeats field "
                        f"{statement.target.id!r}"
                    )
                fields[statement.target.id] = _ModelField(
                    annotation=statement.annotation,
                    required=statement.value is None,
                )
        models[node.name] = fields
    return models


def _validate_value(
    value: Any,
    annotation: ast.expr,
    path: str,
    models: Mapping[str, Mapping[str, _ModelField]],
) -> None:
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            annotation = ast.parse(annotation.value, mode="eval").body
        except SyntaxError as exc:
            raise ValueError(f"{path} has unsupported forward annotation") from exc

    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        errors: list[str] = []
        for option in (annotation.left, annotation.right):
            try:
                _validate_value(value, option, path, models)
                return
            except ValueError as exc:
                errors.append(str(exc))
        raise ValueError(f"{path} does not match any union option: {'; '.join(errors)}")

    if isinstance(annotation, ast.Constant) and annotation.value is None:
        if value is not None:
            raise ValueError(f"{path} must be None")
        return

    if isinstance(annotation, ast.Name):
        primitive = {
            "int": lambda item: type(item) is int,
            "float": lambda item: type(item) in (int, float),
            "bool": lambda item: type(item) is bool,
            "str": lambda item: type(item) is str,
        }.get(annotation.id)
        if primitive is not None:
            if not primitive(value):
                raise ValueError(f"{path} must have type {annotation.id}")
            return
        if annotation.id in models:
            _validate_model(value, annotation.id, path, models)
            return
        raise ValueError(f"{path} uses unsupported type {annotation.id!r}")

    if isinstance(annotation, ast.Subscript) and isinstance(annotation.value, ast.Name):
        container = annotation.value.id
        if container == "list":
            if type(value) is not list:
                raise ValueError(f"{path} must have type list")
            for index, item in enumerate(value):
                _validate_value(item, annotation.slice, f"{path}[{index}]", models)
            return
        if container == "tuple":
            if type(value) is not tuple:
                raise ValueError(f"{path} must have type tuple")
            elements = _subscript_elements(annotation.slice)
            if len(elements) == 2 and isinstance(elements[1], ast.Constant):
                if elements[1].value is Ellipsis:
                    for index, item in enumerate(value):
                        _validate_value(item, elements[0], f"{path}[{index}]", models)
                    return
            if len(value) != len(elements):
                raise ValueError(f"{path} must contain {len(elements)} values")
            for index, (item, item_type) in enumerate(zip(value, elements)):
                _validate_value(item, item_type, f"{path}[{index}]", models)
            return
        if container == "dict":
            if type(value) is not dict:
                raise ValueError(f"{path} must have type dict")
            key_type, value_type = _subscript_elements(annotation.slice)
            for key, item in value.items():
                _validate_value(key, key_type, f"{path}.<key>", models)
                _validate_value(item, value_type, f"{path}[{key!r}]", models)
            return

    raise ValueError(f"{path} uses unsupported annotation {ast.unparse(annotation)!r}")


def _validate_model(
    value: Any,
    model_name: str,
    path: str,
    models: Mapping[str, Mapping[str, _ModelField]],
) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object matching {model_name}")
    fields = models[model_name]
    required = {name for name, field in fields.items() if field.required}
    missing = sorted(required - set(value))
    extra = sorted(set(value) - set(fields))
    if missing or extra:
        raise ValueError(f"{path} has missing fields {missing} and extra fields {extra}")
    for name, item in value.items():
        _validate_value(item, fields[name].annotation, f"{path}.{name}", models)


def _subscript_elements(node: ast.expr) -> tuple[ast.expr, ...]:
    return tuple(node.elts) if isinstance(node, ast.Tuple) else (node,)
