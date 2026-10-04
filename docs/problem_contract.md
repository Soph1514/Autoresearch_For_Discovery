# Problem contract

The `ProblemContract` is the immutable, validated handoff from formalization
and interface extraction to evolutionary search. Shared ownership, budget, and
verification meanings are defined in [shared semantics](shared-semantics.md).

Code lives in:

- `src/the_pigeon_holes/models/problem_contract.py` for preparation and models;
- `src/the_pigeon_holes/execution/signature_extractor.py` for extraction;
- `src/the_pigeon_holes/execution/interface_validation.py` for safe structural
  validation;
- `src/the_pigeon_holes/fitness/` for trusted fitness contracts and registry; and
- `src/the_pigeon_holes/llm/prompts.py` for the generation-facing interface.

## Model

The contract describes a general problem and binds an evaluation suite. A
candidate implements one general `solve(...)` function. The evaluator invokes
it separately on each case and aggregates the resulting metrics according to
the `OptimisationGoal`.

```python
@dataclass(frozen=True)
class ProblemContract:
    natural_language_spec: str
    lean_specification: str
    interface: InterfaceDefinition
    seed_program: str
    evaluation_suite: EvaluationSuite
    optimisation_goal: OptimisationGoal
    resource_limits: ResourceLimits
    fitness_function: FitnessFunctionRef
```

`FitnessFunctionRef` contains the registered function ID, semantic version, and
SHA-256 digest of its implementation. A changed implementation therefore cannot
silently reuse scores from an earlier run.

`InterfaceDefinition` preserves:

- a schema version;
- ordered parameter names and Python types;
- the return type;
- the exact `solve(...)` signature; and
- supporting Pydantic type definitions produced by extraction.

`EvaluationSuite` has a stable ID and one or more uniquely identified cases.
Each case maps every signature parameter to its input value. Stored mappings
and nested lists are immutable. `EvaluationCase.materialize_inputs()` returns
an isolated mutable representation for a future sandbox; mutating it cannot
alter the contract.

`ResourceLimits` separates a per-case timeout from the total candidate-suite
timeout. Memory and iteration limits apply to each sandboxed case. Whole-run
active time and token limits remain `EvolutionLimits`, outside this contract.

## Preparation

```python
build_problem_contract(
    natural_language_spec=...,
    lean_specification=...,
    seed_program=...,
    evaluation_suite_id=...,
    evaluation_cases={"case-id": {"parameter": value}},
    resource_limits=...,
    fitness_function=...,
    model=...,
    client=...,
)
```

Preparation performs these checks before returning:

1. Extract and verify the complete Python interface.
2. Preserve supporting definitions without executing them.
3. Require the seed to contain exactly one synchronous top-level `solve` with
   the exact parameter and return annotations.
4. Require a nonempty suite with unique case IDs.
5. Validate every case key and value against the extracted annotations.
6. Validate nested structured fields by parsing supporting class definitions.
7. Validate nonempty, unique metric names, directions, and aggregation.
8. Validate positive, coherent case/candidate resource limits.
9. Require the referenced fitness function to be registered and compatible with
   the interface, suite, metrics, directions, and aggregation.
10. Recursively freeze the accepted suite data.

The safe validator supports extractor-produced primitives, lists, tuples,
dictionaries, `T | None`, and nested named structured types. Unknown type
syntax fails preparation instead of being guessed or evaluated.

## Information boundaries

The generation prompt contains the general natural-language and Lean context,
supporting type definitions, exact signature, objective, and evolutionary
evidence. It deliberately excludes suite IDs, case values, expected answers,
and fitness-function internals.

The evaluator port receives the complete contract, including cases and
resource limits. It resolves the fitness reference through the operator-owned
registry; request bodies cannot name Python modules. Supporting definitions remain untrusted generated code:
parsing them for a schema is not authorization to execute them in the API
process. The production evaluator may load them only inside its protected
execution environment.

## Verification boundary

Contract preparation verifies Python interface consistency and input shape. It
does not establish that:

- the Lean statement correctly represents the natural-language problem;
- Lean accepted the statement;
- extracted Python types preserve all Lean semantics;
- the seed is mathematically correct; or
- generated candidate code is safe or correct.

Lean checking belongs to the persisted formalization artifact. Custom preparation
requires matching source-hash and checker provenance, stored beside the frozen
contract. Behavioral checking belongs to the registered deterministic fitness
function, while the generic evaluator owns sandbox execution and aggregation.
Custom runs reject an invalid seed before generating candidates.

## Tests

`tests/test_problem_contract.py` covers exact seed compatibility, complete
interface preservation, deep immutability, structured values, metrics, and
limits. `tests/test_contract_evolution_integration.py` verifies that a prepared
structured contract reaches generation and evaluation while hidden case values
do not enter generation prompts.
