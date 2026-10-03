# Problem Contract

The `ProblemContract` is the frozen, validated hand-off between the Lean formalization step and the evolutionary loop. Everything the loop needs to know about a problem is in this object, and nothing in it changes during a run.

Code: `src/the_pigeon_holes/models/problem_contract.py` (contract and builder), `src/the_pigeon_holes/execution/signature_extractor.py` (LLM extraction and verification), `src/the_pigeon_holes/llm/prompts.py` (prompt rendering).

## Why it exists

The Lean statement is **general**: it describes a problem family, such as "pick items under a capacity" for any list of items. The pipeline, though, solves **one instance** at a time, such as the items and capacity for one knapsack. Benchmarking Lean-verified problems only means something if candidate code is written against the general statement and then run on concrete instances. The contract therefore separates the two:

| Source | Contents | Used for |
|---|---|---|
| Lean statement (general) | signature, types, optimisation goal | prompt, verification, scoring direction |
| Instance (specific) | concrete data for one run | evaluation and seed checks |

Candidates are never specialised to an instance. The signature is the same for every instance, which is what stops candidates from hard-coding answers.

## Fields

```python
@dataclass(frozen=True)
class ProblemContract:
    natural_language_spec: str        # the original problem statement, for context
    lean_specification: str           # the verified Lean source the signature came from
    solve_signature: str              # e.g. "def solve(items: list[int], capacity: int) -> list[bool]:"
    seed_program: str                 # starting Python program, defines top-level solve
    instance_id: str                  # identifies this instance, e.g. "knapsack-01"
    instance: Mapping[str, Any]       # concrete data; keys match the signature's parameters
    optimisation_goal: OptimisationGoal
    resource_limits: ResourceLimits
    evaluator_version: str            # version of the scoring code this contract was built for
```

`OptimisationGoal` and `MetricGoal` are defined in `signature_extractor.py` and re-exported by the contract module:

- `OptimisationGoal.primary: MetricGoal`: the main objective.
- `OptimisationGoal.aggregation`: one of `mean`, `median`, `sum`, `worst_case`. How the metric combines across instances.
- `OptimisationGoal.tie_breakers: tuple[MetricGoal, ...]`: secondary metrics, empty by default.
- `MetricGoal.name: str`, `MetricGoal.direction: "maximize" | "minimize"`.

`ResourceLimits` holds `time_seconds`, `memory_mb` and `max_iterations`. These are supplied by the caller, not derived from Lean.

The dataclass is frozen. Attempting to assign a field raises `FrozenInstanceError`.

## How a contract is built

```python
build_problem_contract(
    natural_language_spec=...,
    lean_specification=...,
    seed_program=...,
    instance_id=...,
    instance=...,
    resource_limits=...,
    evaluator_version=...,
    model="claude-sonnet-5-5",   # required; there is no default
    client=None,                 # anthropic.Anthropic; created from ANTHROPIC_API_KEY if None
) -> ProblemContract
```

The steps, in order:

1. **Extract.** `extract_signature(lean_specification, model=...)` sends the Lean text to Claude with a forced tool call, `submit_extracted_interface`. The response yields an `ExtractedInterface`. The function name is always set to `solve` by the code, not taken from the model.
2. **Verify.** `verify_interface_syntax` runs these checks, and raises `ValueError` on the first failure:
   - The function name is `solve`.
   - Every optimisation direction is `maximize` or `minimize`.
   - Parameter names are valid, non-keyword Python identifiers, and unique.
   - The full generated stub parses with `ast.parse`.
   - The `def` line matches the structured fields: same function name, same parameter names in the same order, same parameter types, same return type.
3. **Validate the seed.** `validate_seed_program` checks that the seed parses and defines a top-level `solve`.
4. **Check the instance.** The instance keys must equal the signature's parameter names.
5. **Freeze.** Build and return the `ProblemContract`.

A truncated model response (`stop_reason == "max_tokens"`) raises `RuntimeError` before any parsing.

## How the contract reaches the next agent

`render_solve_contract(contract)` in `llm/prompts.py` returns the block for the code-generation prompt:

- The required function, with its exact signature.
- The objective, for example `minimize makespan (worst_case across instances), ties broken by minimize idle_time.`

The code-generation prompt must include this block verbatim, so every candidate has the same signature.

## What is verified and what is not

Verified in code:
- Names, parameter order and types, return type, goal direction, syntax of the generated stub, seed shape, instance keys.

Not verified:
- **Goal correctness.** The LLM reads the optimisation goal from the Lean statement. A wrong goal with a valid direction string passes. Spot-check the first real extractions by hand.
- **Type-level semantics.** The model's type hints are checked against the signature, not against Lean's meaning. A `Nat` mapped to `int` is accepted even if Lean meant a bounded value.
- **Instance values.** Keys are checked, but not whether values have the right Python types or sizes.
- **Seed behaviour.** The seed is parsed, not run. Running it on the instance needs the execution sandbox, which is not built yet.
- **Pydantic classes.** The extractor produces `pydantic_classes_code`, but the contract does not store it (see Known gaps).

## Known gaps

- **Pydantic classes are dropped.** If the signature uses a Pydantic model, the code-generation prompt refers to a class it never sees. Adding a `data_model_code` field back to the contract and the renderer fixes this.
- **Seed is not executed.** No evaluation of the seed on the instance yet.
- **One instance per contract.** A benchmark over many instances needs one contract per instance, or a change to make `instance` a list. The current choice is one per contract.
- **Live extraction not yet run.** The tests mock the model. A run against the real model with a real knapsack Lean statement has not been done.
- **Plan is out of date.** `docs/superpowers/plans/2026-10-03-problem-contract.md` describes an earlier design (flat goal fields, no instance).

## Running the tests

```bash
.venv/bin/python -m pytest -q
```

The contract tests (`tests/test_problem_contract.py`) and extractor tests (`tests/test_signature_extractor.py`) mock the Anthropic client, so they run without an API key.
