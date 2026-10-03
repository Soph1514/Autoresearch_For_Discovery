

from __future__ import annotations

import ast
import json
import keyword
import textwrap
from dataclasses import dataclass
from typing import Literal

import anthropic

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

# The Anthropic tool schema supplied to Claude when extracting interfaces.
# Claude is required to respond exclusively via this tool so the output is
# machine-parseable.
_EXTRACTION_TOOL = {
    "name": "submit_extracted_interface",
    "description": (
        "Submit the extracted Python interface derived from a Lean 4 "
        "formalization.  This includes the function signature and any Pydantic "
        "model classes required by the signature."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "parameters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Parameter name.",
                        },
                        "python_type": {
                            "type": "string",
                            "description": (
                                "Python 3.10+ type hint string "
                                "(e.g. 'list[tuple[int, int]]')."
                            ),
                        },
                    },
                    "required": ["name", "python_type"],
                },
                "description": "Ordered list of function parameters with types.",
            },
            "return_type": {
                "type": "string",
                "description": "Python 3.10+ return type hint string.",
            },
            "signature_str": {
                "type": "string",
                "description": (
                    "Complete Python def line including type hints and "
                    "trailing colon (e.g. "
                    "'def solve(items: list[int]) -> int:')."
                ),
            },
            "pydantic_classes_code": {
                "type": "string",
                "description": (
                    "Python source for any Pydantic BaseModel classes that "
                    "the signature depends on.  Empty string if none needed."
                ),
            },
            "optimisation_goal": {
                "type": "object",
                "description": "The optimisation goal stated by the Lean statement.",
                "properties": {
                    "primary": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Name of the metric."},
                            "direction": {"type": "string", "enum": ["maximize", "minimize"]},
                        },
                        "required": ["name", "direction"],
                    },
                    "aggregation": {
                        "type": "string",
                        "enum": ["mean", "median", "sum", "worst_case"],
                        "description": "How the metric is combined across evaluation cases.",
                    },
                    "tie_breakers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "direction": {"type": "string", "enum": ["maximize", "minimize"]},
                            },
                            "required": ["name", "direction"],
                        },
                        "description": "Secondary metrics used to break ties; empty if none.",
                    },
                },
                "required": ["primary", "aggregation"],
            },
        },
        "required": [
            "parameters",
            "return_type",
            "signature_str",
            "pydantic_classes_code",
            "optimisation_goal",
        ],
    },
}

FUNCTION_NAME = "solve"


_SYSTEM_PROMPT = textwrap.dedent("""\
    You are an expert at translating Lean 4 mathematical formalizations into
    Python function signatures with precise type hints.

    RULES
    -----
    • The function name MUST be exactly "solve".

    • Parameter names MUST be valid Python identifiers. Convert Lean names
      with this rule: replace every ' with _prime (n' -> n_prime), and add a
      trailing _ to Python keywords (from -> from_).

    • Map Lean types to Python 3.10+ type hints using this table:
      Nat / UInt32 / Int  →  int
      Float / Real        →  float
      Bool                →  bool
      String              →  str
      List α              →  list[T]
      α × β  (Prod)       →  tuple[T, U]
      Option α            →  T | None

    • For Lean ``structure`` declarations, emit Pydantic ``BaseModel``
      classes.  Include ``model_rebuild()`` calls when classes reference
      each other.

    • Identify the optimisation goal from the Lean statement: the primary metric
      and whether it is maximised or minimised, how it is aggregated across
      evaluation cases, and any tie-breaking metrics. If the statement expresses no
      goal, do not guess one.

    • Respond ONLY by calling the ``submit_extracted_interface`` tool.
      Do NOT include any free-text explanation.
""")


@dataclass(frozen=True)
class Parameter:
    """A single function parameter with its Python type annotation."""

    name: str
    python_type: str


@dataclass(frozen=True)
class MetricGoal:
    name: str
    direction: Literal["maximize", "minimize"]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("metric name cannot be empty")
        if self.direction not in ("maximize", "minimize"):
            raise ValueError("metric direction must be 'maximize' or 'minimize'")


@dataclass(frozen=True)
class OptimisationGoal:
    primary: MetricGoal
    aggregation: Literal["mean", "median", "sum", "worst_case"]
    tie_breakers: tuple[MetricGoal, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tie_breakers", tuple(self.tie_breakers))
        if not isinstance(self.primary, MetricGoal) or not all(
            isinstance(metric, MetricGoal) for metric in self.tie_breakers
        ):
            raise ValueError("optimisation metrics must be MetricGoal values")
        if self.aggregation not in ("mean", "median", "sum", "worst_case"):
            raise ValueError(
                "metric aggregation must be mean, median, sum, or worst_case"
            )
        names = [self.primary.name, *(metric.name for metric in self.tie_breakers)]
        if len(names) != len(set(names)):
            raise ValueError("primary and tie-breaker metric names must be unique")


@dataclass
class ExtractedInterface:
    """The complete Python interface derived from a Lean 4 formalization.

    Attributes
    ----------
    function_name:
        Name of the Python function (mirrors the Lean declaration name).
    parameters:
        Ordered list of parameters with Python type hints.
    return_type:
        Python type-hint string for the return value.
    signature_str:
        The full ``def …:`` line ready for insertion into source code.
    pydantic_classes_code:
        Python source for any Pydantic ``BaseModel`` helper classes.
        Empty string when none are needed.
    """

    function_name: str
    parameters: list[Parameter]
    return_type: str
    signature_str: str
    pydantic_classes_code: str
    optimisation_goal: OptimisationGoal

    # -- code generation ----------------------------------------------------

    def to_interface_code(self) -> str:
        """Return an executable Python source string for the full interface.

        The output includes (in order):
          1. ``from pydantic import BaseModel`` (if Pydantic classes exist).
          2. Any Pydantic ``BaseModel`` class definitions.
          3. The function signature with ``...`` as the body.

        The returned string is guaranteed to pass ``ast.parse``.
        """
        parts: list[str] = []

        if self.pydantic_classes_code:
            parts.append("from pydantic import BaseModel\n")
            parts.append(self.pydantic_classes_code.rstrip())
            parts.append("")  # blank line separator

        # Build the function stub
        func_lines: list[str] = [self.signature_str, "    ..."]

        parts.append("\n".join(func_lines))

        return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Syntax verification
# ---------------------------------------------------------------------------


def _normalize_type(type_str: str) -> str:
    """Return a canonical form of a type-hint string (whitespace-insensitive)."""
    try:
        return ast.unparse(ast.parse(type_str, mode="eval").body)
    except SyntaxError as exc:
        raise ValueError(f"Invalid type hint string {type_str!r}: {exc}") from exc


def _check_identifier(identifier: str, kind: str, function_name: str) -> None:
    """Reject names that are not usable Python identifiers.

    Lean allows names such as ``n'`` or ``from`` that Python does not, so
    these are reported explicitly rather than surfacing as a generic syntax error.
    """
    if not identifier.isidentifier() or keyword.iskeyword(identifier):
        raise ValueError(
            f"ExtractedInterface for '{function_name}': {kind} {identifier!r} "
            "is not a valid Python identifier"
        )


def _check_names(interface: ExtractedInterface) -> None:
    """Check that the function and parameter names are usable Python names.

    Runs before parsing so that a bad name is reported as such, not as a
    generic syntax error.
    """
    name = interface.function_name
    if name != FUNCTION_NAME:
        raise ValueError(
            f"ExtractedInterface function name is {name!r}, must be {FUNCTION_NAME!r}"
        )
    goal = interface.optimisation_goal
    for metric in (goal.primary, *goal.tie_breakers):
        if metric.direction not in ("maximize", "minimize"):
            raise ValueError(
                f"ExtractedInterface for '{name}' has direction {metric.direction!r}; "
                "must be 'maximize' or 'minimize'"
            )
    for param in interface.parameters:
        _check_identifier(param.name, "parameter name", name)
    names = [p.name for p in interface.parameters]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(
            f"ExtractedInterface for '{name}' has duplicate parameter names: {duplicates}"
        )


def _check_signature_matches(interface: ExtractedInterface) -> None:
    """Check that ``signature_str`` agrees with the structured fields.

    Verifies the function name, parameter names and order, each parameter's
    annotation, and the return annotation against ``function_name``,
    ``parameters`` and ``return_type``.

    Raises
    ------
    ValueError
        If any of these disagree, listing every mismatch found.
    """
    name = interface.function_name
    try:
        sig_tree = ast.parse(f"{interface.signature_str}\n    ...")
    except SyntaxError as exc:
        raise ValueError(
            f"ExtractedInterface for '{name}' has an invalid signature_str: {exc}"
        ) from exc

    if len(sig_tree.body) != 1 or not isinstance(sig_tree.body[0], ast.FunctionDef):
        raise ValueError(
            f"ExtractedInterface for '{name}': signature_str must be a single def statement"
        )
    fn = sig_tree.body[0]
    errors: list[str] = []

    if fn.name != name:
        errors.append(f"function name is '{fn.name}', expected '{name}'")

    # Collect every parameter in declaration order, including *args / **kwargs.
    actual_args = [
        *fn.args.posonlyargs,
        *fn.args.args,
        *([fn.args.vararg] if fn.args.vararg else []),
        *fn.args.kwonlyargs,
        *([fn.args.kwarg] if fn.args.kwarg else []),
    ]
    actual_names = [a.arg for a in actual_args]
    expected_names = [p.name for p in interface.parameters]

    if actual_names != expected_names:
        errors.append(f"parameter names {actual_names} do not match {expected_names}")
    else:
        for arg, param in zip(actual_args, interface.parameters):
            want = _normalize_type(param.python_type)
            if arg.annotation is None:
                errors.append(f"parameter '{param.name}' has no annotation")
            elif (got := ast.unparse(arg.annotation)) != want:
                errors.append(f"parameter '{param.name}' is '{got}', expected '{want}'")

    want_return = _normalize_type(interface.return_type)
    if fn.returns is None:
        got_return = "None" if want_return == "None" else "<missing>"
    else:
        got_return = ast.unparse(fn.returns)
    if got_return != want_return:
        errors.append(f"return annotation is '{got_return}', expected '{want_return}'")

    if errors:
        raise ValueError(
            f"ExtractedInterface for '{name}' has an inconsistent signature: "
            + "; ".join(errors)
        )


def verify_interface_syntax(interface: ExtractedInterface) -> bool:
    """Verify that the extracted interface is valid and internally consistent.

    Checks, in order:

    1. Function and parameter names are valid, non-keyword Python identifiers,
       and parameter names are unique.
    2. The full interface code (Pydantic models + function stub) parses with
       :func:`ast.parse`.
    3. ``signature_str`` defines a function named ``function_name``.
    4. Its parameter names, order, and annotations match ``parameters``.
    5. Its return annotation matches ``return_type``.

    Returns ``True`` on success.

    Raises
    ------
    ValueError
        If any check fails.
    """
    _check_names(interface)
    code = interface.to_interface_code()
    try:
        ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(
            f"ExtractedInterface for '{interface.function_name}' "
            f"failed Python syntax verification: {exc}"
        ) from exc
    _check_signature_matches(interface)
    return True


# ---------------------------------------------------------------------------
# LLM-based extraction
# ---------------------------------------------------------------------------


def _parse_goal(raw: dict) -> OptimisationGoal:
    """Convert the model's goal object into an OptimisationGoal."""
    return OptimisationGoal(
        primary=MetricGoal(**raw["primary"]),
        aggregation=raw["aggregation"],
        tie_breakers=tuple(MetricGoal(**t) for t in raw.get("tie_breakers", [])),
    )


def extract_signature(
    lean_code: str,
    *,
    model: str,
    client: anthropic.Anthropic | None = None,
) -> ExtractedInterface:
    """Extract a Python interface from a verified Lean 4 declaration.

    Sends *lean_code* to Claude via the Anthropic messages API with the
    ``submit_extracted_interface`` tool and parses the structured response
    into an :class:`ExtractedInterface`.

    Parameters
    ----------
    lean_code:
        The raw Lean 4 source text (e.g. structure definitions +
        ``def solve …``).
    model:
        The Anthropic model identifier to use (e.g. ``"claude-sonnet-5-5"``).
        Required; there is no default.
    client:
        An :class:`anthropic.Anthropic` instance.  When ``None`` a new
        client is created from the ``ANTHROPIC_API_KEY`` env-var.

    Returns
    -------
    ExtractedInterface
        The parsed interface ready for code generation and verification.

    Raises
    ------
    RuntimeError
        If the model response does not contain the expected tool-use block.
    """
    if client is None:
        client = anthropic.Anthropic()

    user_message = (
        "Extract the Python function signature and any required Pydantic "
        "classes from the following Lean 4 formalization.  Respond ONLY "
        "by calling the submit_extracted_interface tool.\n\n"
        f"```lean\n{lean_code}\n```"
    )

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        tools=[_EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "submit_extracted_interface"},
        messages=[{"role": "user", "content": user_message}],
    )

    # A truncated response may carry a partial tool input that is missing fields.
    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            "Claude response was truncated at max_tokens; the extracted interface is incomplete."
        )

    # Find the tool-use block in the response
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "submit_extracted_interface":
            data = block.input
            return ExtractedInterface(
                function_name=FUNCTION_NAME,
                parameters=[
                    Parameter(name=p["name"], python_type=p["python_type"])
                    for p in data["parameters"]
                ],
                return_type=data["return_type"],
                signature_str=data["signature_str"],
                pydantic_classes_code=data.get("pydantic_classes_code", ""),
                optimisation_goal=_parse_goal(data["optimisation_goal"]),
            )

    raise RuntimeError(
        "Claude response did not contain a 'submit_extracted_interface' "
        "tool-use block.  Raw response content: "
        f"{json.dumps([str(b) for b in response.content])}"
    )
