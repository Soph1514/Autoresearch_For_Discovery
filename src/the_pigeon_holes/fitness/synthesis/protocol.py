"""The frozen contract a synthesised scorer must satisfy.

Everything here is host-authored. The model writes only the three functions
described by `PROTOCOL_DOC`; it never chooses the aggregation, the tie-breakers,
the deadlines, the container policy or the failure taxonomy, because a subtle
error in any of those corrupts the search silently.

Nothing in this module imports, compiles or executes synthesised source. The
static gate parses with `ast.parse` only, and the wrapper text is a string that
is shipped to a container.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from fractions import Fraction

from the_pigeon_holes.execution.signature_extractor import OptimisationGoal

from ..base import CaseFitness

SYNTHESIS_VERSION = "synthesised-fitness-v1"
WRAPPER_ENTRY = "__pigeonholes_verdict"
REQUIRED_FUNCTIONS = ("validate", "score", "descriptor")
MAX_SOURCE_BYTES = 64 * 1024

# The worker image is stock CPython with nothing installed, so a scorer that
# imports anything else fails inside the container. Rejecting it here turns a
# late container crash into an early, explainable defect.
ALLOWED_IMPORTS = frozenset({
    "bisect", "cmath", "collections", "decimal", "fractions", "functools",
    "heapq", "itertools", "math", "numbers", "operator", "statistics", "string",
})
FORBIDDEN_NAMES = frozenset({
    "__import__", "eval", "exec", "compile", "open", "globals", "locals",
    "vars", "input", "breakpoint", "memoryview",
})

PROTOCOL_DOC = """\
Write a Python module defining exactly these three top-level functions:

    def validate(output, **case_inputs) -> str | None
        Return None when `output` is a feasible solution for this case.
        Otherwise return a short non-empty string saying which rule it breaks.
        Never raise: an unexpected input shape is an invalid output, not an error.

    def score(output, **case_inputs) -> dict
        Only called when validate returned None. Return every configured metric
        name mapped to an EXACT rational: an int, a fractions.Fraction, or a
        string "numerator/denominator". Floats are rejected as inexact.

    def descriptor(output, **case_inputs) -> tuple[float, ...]
        Return coordinates describing the SHAPE of the solution, not its quality.
        These place the candidate in a diversity niche. The tuple length must
        equal the descriptor_arity you declare, and every value must be finite.

Rules:
  - The standard library only, and only these modules: {allowed}.
  - No top-level statements other than imports, constants and helper defs.
  - No file, network, process or environment access.
  - `case_inputs` arrives as keyword arguments named exactly: {parameters}.
  - `output` is whatever the candidate's solve(...) returned, already decoded
    from JSON, so a list is a list and a tuple arrives as a list.
"""

# Appended AFTER the model's source so this definition wins the namespace lookup.
# Each stage is isolated so a defect in the scorer is reported as a defect rather
# than silently becoming an "invalid candidate" verdict.
WRAPPER_SOURCE = '''

def __pigeonholes_verdict(payload):
    from fractions import Fraction as _Fraction

    output = payload["output"]
    case_inputs = payload["case_inputs"]

    def _defect(where, error, message=None):
        return {"kind": "defect", "where": where,
                "type": type(error).__name__ if error is not None else "ProtocolError",
                "message": (message if message is not None else str(error))[:500]}

    try:
        reason = validate(output, **case_inputs)
    except BaseException as error:
        return _defect("validate", error)
    if reason is not None:
        if not isinstance(reason, str) or not reason.strip():
            return _defect("validate", None, "validate must return None or a non-empty string")
        return {"kind": "invalid", "reason": reason.strip()[:500]}

    try:
        metrics = score(output, **case_inputs)
    except BaseException as error:
        return _defect("score", error)
    if not isinstance(metrics, dict):
        return _defect("score", None, "score must return a dict")
    pairs = {}
    for name, value in metrics.items():
        if isinstance(value, bool) or isinstance(value, float):
            return _defect("score", None, "metric %r must be exact, not a float" % (name,))
        try:
            exact = _Fraction(value)
        except BaseException as error:
            return _defect("score", error, "metric %r is not an exact rational" % (name,))
        pairs[str(name)] = [str(exact.numerator), str(exact.denominator)]

    try:
        axes = descriptor(output, **case_inputs)
    except BaseException as error:
        return _defect("descriptor", error)
    try:
        coordinates = [float(value) for value in axes]
    except BaseException as error:
        return _defect("descriptor", error, "descriptor must be a sequence of numbers")
    for value in coordinates:
        if value != value or value in (float("inf"), float("-inf")):
            return _defect("descriptor", None, "descriptor values must be finite")

    return {"kind": "valid", "metrics": pairs,
            "descriptor": [repr(value) for value in coordinates]}
'''


@dataclass(frozen=True)
class Defect:
    """The scorer itself misbehaved. Never confused with an invalid candidate."""

    where: str
    type: str
    message: str

    def describe(self) -> str:
        return f"{self.where}: {self.type}: {self.message}"


def metric_names(goal: OptimisationGoal) -> tuple[str, ...]:
    """Every metric the evaluator will look for, primary first."""
    return (goal.primary.name, *(tie.name for tie in goal.tie_breakers))


def parse_verdict(payload: object, goal: OptimisationGoal, arity: int) -> CaseFitness | Defect:
    """Turn one container verdict into a CaseFitness, or say the scorer is broken.

    This is the only place a container payload becomes a score, so every shape
    that is not exactly right is a Defect rather than a silently wrong number.
    """
    if not isinstance(payload, dict):
        return Defect("envelope", "ProtocolError", "verdict was not an object")
    kind = payload.get("kind")

    if kind == "defect":
        return Defect(str(payload.get("where", "unknown")), str(payload.get("type", "Error")),
                      str(payload.get("message", "")))

    if kind == "invalid":
        reason = payload.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            return Defect("validate", "ProtocolError", "invalid verdict carried no reason")
        return CaseFitness(False, failure_reason=reason.strip())

    if kind != "valid":
        return Defect("envelope", "ProtocolError", f"unknown verdict kind {kind!r}")

    raw_metrics = payload.get("metrics")
    if not isinstance(raw_metrics, dict):
        return Defect("score", "ProtocolError", "valid verdict carried no metrics object")
    expected = set(metric_names(goal))
    if set(raw_metrics) != expected:
        missing = sorted(expected - set(raw_metrics))
        extra = sorted(set(raw_metrics) - expected)
        return Defect("score", "ProtocolError",
                      f"metric names must be exactly {sorted(expected)}; "
                      f"missing {missing}, unexpected {extra}")
    metrics: dict[str, Fraction] = {}
    for name, pair in raw_metrics.items():
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            return Defect("score", "ProtocolError", f"metric {name!r} is not a numerator/denominator pair")
        try:
            numerator, denominator = int(pair[0]), int(pair[1])
        except (TypeError, ValueError):
            return Defect("score", "ProtocolError", f"metric {name!r} is not an integer pair")
        if denominator == 0:
            return Defect("score", "ProtocolError", f"metric {name!r} has a zero denominator")
        metrics[name] = Fraction(numerator, denominator)

    raw_descriptor = payload.get("descriptor")
    if not isinstance(raw_descriptor, (list, tuple)) or len(raw_descriptor) != arity:
        return Defect("descriptor", "ProtocolError",
                      f"descriptor must have exactly {arity} values")
    try:
        descriptor = tuple(float(value) for value in raw_descriptor)
    except (TypeError, ValueError):
        return Defect("descriptor", "ProtocolError", "descriptor values are not numbers")

    # CaseFitness re-validates finiteness; a non-finite value raises here rather
    # than reaching the archive.
    try:
        return CaseFitness(True, metrics=metrics, behavioral_descriptor=descriptor)
    except ValueError as error:
        return Defect("envelope", "ProtocolError", str(error))


def static_gate(source: str, *, declared_metrics: tuple[str, ...], arity: int,
                goal: OptimisationGoal) -> tuple[str, ...]:
    """Parse-only conformance check. Returns the problems found, empty when clean.

    Uses `ast.parse`; never `compile(..., "exec")` and never `exec`. A candidate
    that fails here is recorded and shown to the human, not executed.
    """
    problems: list[str] = []

    if len(source.encode()) > MAX_SOURCE_BYTES:
        return (f"source exceeds {MAX_SOURCE_BYTES} bytes",)
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return (f"source does not parse: {error}",)

    defined = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    for name in REQUIRED_FUNCTIONS:
        if name not in defined:
            problems.append(f"missing required function {name}()")
    if any(isinstance(node, ast.AsyncFunctionDef) and node.name in REQUIRED_FUNCTIONS
           for node in tree.body):
        problems.append("the three protocol functions must be synchronous")

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom,
                             ast.Assign, ast.AnnAssign, ast.Pass)):
            continue
        # A bare expression is only a docstring; anything else is a side effect.
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        problems.append(f"unexpected top-level {type(node).__name__}; "
                        "only imports, constants and defs are allowed")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_IMPORTS:
                    problems.append(f"import of {alias.name!r} is outside the allowed standard library")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if node.level or root not in ALLOWED_IMPORTS:
                problems.append(f"import from {node.module!r} is outside the allowed standard library")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            problems.append(f"use of {node.id!r} is not allowed in a scorer")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            problems.append(f"access to dunder attribute {node.attr!r} is not allowed")

    expected = metric_names(goal)
    if tuple(declared_metrics) != expected:
        problems.append(f"declared metrics {list(declared_metrics)} do not match the "
                        f"optimisation goal {list(expected)}")
    if arity < 1:
        problems.append("descriptor_arity must be at least 1")

    return tuple(dict.fromkeys(problems))
