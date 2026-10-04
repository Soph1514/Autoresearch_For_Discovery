# Lean fitness compiler

Trusted problem scorers keep their existing path. For a missing scorer, formalize
once, run the compiler to produce a verified evaluator, then execute feasibility
and objective **in Lean**. Freeze this evaluator before search.
There is no generated Python scoring formula and no model call during scoring.

## Decision and inspected outputs

The existing Lea CLI is a tool-using prover. The hosted generation service actually
uses base Qwen3-4B; the fine-tuned service judges translation fidelity. Neither is
an executable-evaluator generator. The saved knapsack formalization defines
feasibility, objective, and an optimality predicate over `Finset (Fin n)`.
Autocorrelation mixes noncomputable real integrals with finite list definitions;
its finite objective's optimization direction appears only in a comment. The
ProofNet files include abstract algebra/topology theorems with proof holes.
Compilation alone does not supply an executable scorer for these examples.

We considered execution, AST-to-Python translation, and an optimization IR.
Direct Lean execution has the smallest semantic translation surface. The compiler inspects elaborated
expressions to identify the candidate, feasibility, objective, and direction. A second arithmetic interpreter/IR would add a second
semantics to validate without making more of these real outputs executable.

## Accepted subset

An ordinary definition of an optimality predicate, with instance parameters first
and candidate last, or a definition/theorem asserting existence of an optimum:

```lean
def optimal (capacity : Nat) (chosen : List Nat) : Prop :=
  chosen.sum ≤ capacity ∧
    ∀ other, other.sum ≤ capacity → other.sum ≤ chosen.sum
```

Types: `Nat`, `Int`, `List Nat`, `List Int`. Objective: `Nat` or `Int`.
Feasibility must have a computable `Decidable` instance. The relation must be
`F candidate ∧ ∀ alternative, F alternative → O alternative ≤ O candidate`
(maximize), or its reversed comparison (minimize). Definitions can be unfolded;
the alternative must have the same type, feasibility and objective. Multiple
matching declarations, candidate-independent objectives, proof-dependent
constraints, implicit dependent dimensions, arbitrary theorem shapes, custom
structures, reals, and optimization goals stated only in comments are rejected.
No custom `Bool`/`Int` formalizer interface is required.

The conservative source gate uses Lean's parser before elaboration. It permits
ordinary definitions/theorems, namespaces, opens, and pinned standard/Mathlib
imports. It excludes tactic blocks, attributes, metaprogramming, custom syntax,
unsafe/partial/noncomputable declarations, and proof holes. This sacrifices
coverage deliberately; it is not a general sandbox for hostile Lean programs.

## Guarantees and boundaries

The compiler checks its output against the original optimization declaration using a
kernel-checked definitional equivalence (`Iff.rfl`). Each score is executed in
Lean, then checked again by kernel reduction against the same expressions.
Execution/certificate disagreement rejects the result. Infeasible or malformed
candidates receive no objective metric.

This establishes correspondence with the **accepted Lean specification**, not
with the English statement. English fidelity remains a formalizer/review trust
boundary. Lean compilation is recorded separately from that unproven fidelity.
The Lean kernel, pinned libraries, host tools and repository-owned compiler are
trusted. Kernel reduction can be slow; unsupported or resource-exhausting
specifications fail closed. The existing evolution layer aggregates exact case
scores as floats, so the fallback limits returned objectives to exactly
representable integers.

Lean's [elaborated expressions](https://lean-lang.org/doc/api/Lean/Expr.html)
and [weak-head normalization](https://lean-lang.org/doc/api/Lean/Meta/WHNF.html)
provide the structural inspection. The separate reduction certificate matters
because Lean's [runtime implementation overrides](https://lean-lang.org/doc/api/Lean/Compiler/ImplementedByAttr.html)
can differ from what the kernel reduces. The compiler uses the installed 4.19 APIs.

## Use and artifacts

The pipeline stages are **formalizer → compiler → evolution and scoring**.
The compiler includes optimization analysis, evaluator generation, correspondence
checking and freezing. Lean's own compilation/type-checking is used within this step.

The direct API for an existing Lean specification is
`the_pigeon_holes.fitness.compiler.compile_fitness(...)`.
`formalize_and_compile(...)` first invokes Lea, then runs this compiler.


```python
from pathlib import Path
from the_pigeon_holes.pipeline.runner import autoresearch

summary = await autoresearch(
    problem_name="subset-sum",
    statement=Path("problems/subset_sum/problem.txt").read_text(),
    instance={"weights": [3, 4, 5], "capacity": 7},
    lean_project=Path("problems/lean"),
    run_dir=Path("runs/my-subset-sum"),
    model="claude-sonnet-4-6",
    max_minutes=2,
)
```

`prepare_autoresearch` runs initialization without search; `run_prepared` starts
search with that exact contract and registry. Operator-provided scorers can pass
their `trusted_contract` and registry. An invalid trusted contract fails rather
than switching to a generated scorer. Unknown problems use Lea by default; a
different existing formalizer can be injected as `(statement, output_dir) -> Path`.
The generated scorer has no formalizer reference.

Inputs are JSON objects with keys matching Lean instance parameter names, not a
second ambiguous NL description. Parameters are passed to the Python solver in
the order determined by the compiler. The fallback builds a typed empty/zero seed; the existing
repair loop can improve an invalid seed without rewarding it. The workbench, engine composer and CLI all use this compiler. The frontend's
existing `ui/preparation.py` prepares the contract; CLI orchestration lives in
`pipeline/runner.py`. There is no separate `pipeline/autoresearch.py`.

`runs/<run>/fitness/` contains the formalizer request/logs and a unique evaluator
directory with `Generated.lean`, the accepted `Specification.lean`, `Compiler.lean`,
`Compile.lean`, `CompiledFitness.lean`, compiled modules, and `manifest.json`. The manifest
records the input, schema, normalized expressions, direction, model provenance,
toolchain, dependency revisions, implementation/file hashes and validation result.
The manifest digest is the fitness reference. Scoring verifies content hashes and
rejects changed artifacts or implementations. Restart with
`load_lean_fitness(artifact_dir, contract.fitness_function)` and register the
returned scorer; arbitrary artifact directories are never auto-discovered/trusted.

Failures are persisted as `formalization_failed`, `lean_compile_failed`,
`unsupported_formalization`, `compiler_failed`, or
`evaluator_validation_failed`. Nothing falls back to an LLM judge.

## Reproduce

Use the repository's normal Python/Lean setup from the main README. Replay the
saved, unedited live Lea output without generating it again:

```sh
uv run python scripts/run_lean_fitness.py
uv run python -m pytest tests/test_fitness_compiler.py -q
```

Generate anew using `ANTHROPIC_API_KEY` from `.env`:

```sh
uv run python scripts/run_lean_fitness.py --live --lea-model anthropic/claude-sonnet-4-6
```

Add `--search-model claude-sonnet-4-6 --max-minutes 2` to evolve solvers after
preparation. This uses the existing Docker worker and requires its daemon/image.
Candidate programs run in the container; Lean scoring runs on the host with a
per-process timeout and heartbeat limit. Concurrent calls use separate temporary
query files and share only the frozen modules.

The checked-in example was generated by Lea with Claude Sonnet 4.6, not Qwen:
the hosted Qwen service was unavailable locally without Modal credentials. The
generation metadata records 34.811 seconds, 40,828 tokens and an estimated
$0.142 from Lea's log. With `[3, 4, 5]` and capacity `7`, `[1, 1, 0]` is feasible
with objective `7`; `[0, 1, 1]`, `[1, 0]`, and nonbinary candidates are rejected.
These scores have local kernel certificates, not an English-equivalence proof.

Validation on this branch: 26 real Lean compiler tests passed; the existing suite
passed 266 tests with 19 Docker-dependent skips. The compiler unit integration test runs
the actual evolution engine and Lean scorer with stubbed generation/container
ports, verifying that seed and offspring share one evaluator digest. Frontend
integration also passes with the real Docker worker and scripted proposals,
including repair of an infeasible initial candidate and unchanged scorer hashes.
The local wheel build includes the compiler and example data without warnings.

## Frontend flow

After formalization/checking, choose a **Problem family** in either composer.
Existing families use the registered scorer (and its baseline if no seed is
provided). **New problem — Lean compiler** sends the saved formalization
ID and reviewed instance inputs to `POST /api/contracts`. This route compiles that exact
checked source; it never repeats a model call. All existing source-hash and
alignment-review gates still apply.

The new-problem form takes the general problem and a specific instance in natural
language. After Lean checking, Claude converts that instance to JSON; users review
the Lean and JSON before compilation. These are the actual research inputs. If the
conversion fails or inputs are missing, preparation requires corrected JSON rather
than substituting starter cases. The compiler validates the reviewed inputs against
its extracted interface. This does not establish that the JSON matches the English.

For older saved general specifications without an instance description, or API
clients that omit it, leaving **Evaluation cases** empty still generates up to five
starter instances during preparation. A deterministic, bounded search proposes small inputs from the Lean
parameter types. Only instances with a Lean-certified feasible witness are kept;
the certificates are saved in `GeneratedCases.lean`. No model call is used. The
returned cases populate the editable form. Edits invalidate the prepared contract;
prepare again to save the edited suite before starting research. Registered
scorers still require their own case inputs.

Cases supply concrete inputs on which candidate algorithms are executed and
compared; they do not prove correctness for all inputs. The generated suite is a
starter suite, not a representative benchmark or proof of optimality. If the
bounded search finds no feasible instance, preparation reports
`test_case_generation_failed` and accepts manually supplied cases instead.

The compiler creates and freezes the evaluator before the contract is saved.
The form shows success or a structured compiler failure, the solve signature,
objective/direction, and a **View compiler result** link to
`GET /api/contracts/{id}/compiler`. This includes provenance, source and validation.

`POST /api/runs` reloads the accepted evaluator from a server-owned `fitness`
record in the existing artifact store, verifies its hashes against the contract,
and uses it for the seed and all descendants. It performs no compilation or
formalization. Both the database and its sibling `fitness/` directory must be
retained across restarts. Missing or modified files prevent the run from starting.
The engine identifies the scorer as **Lean compiler**. An infeasible compiler
seed can be repaired; it never receives a valid score. Trusted scorer seed rules
are unchanged.

The local compiler uses `problems/lean` by default; `RESEARCH_LEAN_PROJECT` can
point to another configured project. Compilation needs local Lean/Lake and the
project's dependencies. Docker and `RESEARCH_MODEL`/provider credentials are
needed to start evolution, not to compile an already saved specification.

Frontend validation: the full Python suite passed 297 tests (19 Docker-dependent
checks skipped in the restricted test process). All six HTTP compiler integration
cases then passed with Docker access, including real worker execution. The
frontend build and 13 frontend tests pass. Browser checks exercise compilation in
the workbench and the engine composer, using a saved checked specification rather
than paid hosted generation.

Chrome also completed the engine-composer flow through **Start research**, real
Docker execution, and Lean scoring: the scripted subset-sum proposal scored 7,
and its kernel certificate and compiler verification link appeared in the engine
without console errors. The proposal was scripted, not generated by a live model.
