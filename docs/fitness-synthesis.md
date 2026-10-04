# Human-reviewed fitness synthesis

Status: implemented on `feat/hitl`. Covers the fallback used when
[the Lean fitness compiler](fitness-compiler.md) cannot express a checked
statement. The design it narrows is [judge-synthesis.md](judge-synthesis.md).

## When it runs

`compile_fitness` accepts a deliberately small Lean language: `Nat`, `Int`,
`List Nat`, `List Int`. Anything else raises
`LeanFitnessError(stage="unsupported_formalization")`, which used to be a dead
end — no scorer, no contract, no run.

Only that stage triggers synthesis. `POST /api/contracts` turns it into **409**
with `{"synthesis_required": true, ...}`; every other compiler stage stays 422.
A deterministic, kernel-checked scorer is never replaced by a model-written one.

## The loop

```
two independent syntheses -> critic recommends one -> human accepts or rejects
        ^                                                     |
        +------------------ rejection feedback ---------------+
```

Three rounds maximum. Rejecting the third round ends the session `exhausted`:
nothing is registered, no contract is created, and `resolve()` keeps failing
closed. The human can abandon at any round.

**Independence is structural.** Current models reject `temperature`, and one
model prompted twice produces near-duplicates, which would make the critic's
choice meaningless. So candidate A is written by `claude-opus-5-5` from the Lean
statement as primary source, and candidate B by `claude-sonnet-4-6` from the
natural-language statement and extracted interface, reconciled against Lean
afterwards. Both models must be priced in `llm/budget.py`, because
`ProviderTokenBudget` refuses an unbudgeted call.

**The critic reads; it does not run anything.** Its recommendation is an
argument, not a measurement. It never fails a round: an unparseable reply leaves
`chosen: null` and the human compares the two modules directly.

## What the model writes

Not a `FitnessFunction`. Three pure functions, in a module:

```python
def validate(output, **case_inputs) -> str | None     # None when feasible
def score(output, **case_inputs) -> dict              # exact rationals only
def descriptor(output, **case_inputs) -> tuple[float, ...]
```

The model does not choose the aggregation, the tie-breakers, the deadlines, the
container policy, the failure taxonomy or the repair decision. Those are already
written and tested, and a subtle error in any of them corrupts the search
silently.

`fitness/synthesis/protocol.py` owns the frozen text, the host-authored wrapper
and `parse_verdict`. The wrapper is appended *after* the model's source so its
definition wins the namespace lookup, and it isolates each of the three calls so
that a raised exception becomes a **defect of the scorer**, never an "invalid
candidate" verdict — confusing those would route a broken scorer into the
candidate repair path. Metrics cross the container boundary as
numerator/denominator string pairs and become `Fraction` on the host, so exact
rationals survive aggregation.

A parse-only static gate (`ast.parse`, never `compile` or `exec`) rejects
non-stdlib imports, top-level side effects, `eval`/`exec`/`open`/dunder access,
sources over 64 KB, declared metrics that do not match the goal, and a
descriptor arity below one. A failing candidate is recorded and shown to the
human, not executed.

## Security invariant

**Synthesised code executes only inside the worker container, never on the host.**

`evaluate_case` reads `scorer.py` from disk, concatenates the wrapper, and writes
the result to a container's stdin. It never calls `compile`, `exec`,
`importlib` or `runpy`. `freeze_scorer`'s admission probe goes through a real
container. `make_evaluator` reloads a scorer by reading JSON and hashing bytes.
The review panel builds DOM nodes and assigns `textContent`; a test asserts the
module contains no `.innerHTML`. The scorer route serves `text/plain` with
`Content-Disposition: attachment` and `X-Content-Type-Options: nosniff`.

`FitnessFunction.evaluate_case` is synchronous and the evaluator calls it through
`asyncio.to_thread`, so the adapter runs its own loop in that thread. Called from
a thread that already has one it raises a named error rather than failing
obscurely — which is how the `POST /review` route was caught running the freeze
probe on the event loop; that route now goes through `asyncio.to_thread`.

## Freezing and the digest chain

`freeze_scorer` mirrors `compile_fitness`: a uuid4 workspace holding `scorer.py`,
`rejected.py`, `lean.lean`, `review.json` and `manifest.json`; one real container
probe before admission; then `status: "accepted"`.

```
scorer.py bytes -> manifest["files"] -> manifest.json bytes
  -> implementation_sha256 -> contract.fitness_function
```

One edited byte fails both `_integrity()` and the registry's `resolve()`. The
manifest's `implementation_sha256` also covers `adapter.py` + `protocol.py`, so
changing the wrapper or the verdict parser invalidates every frozen scorer.

## Session state and restarts

Persisted under artifact kind `synthesis`. States: `extracting`, `generating`,
`criticising`, `awaiting_review`, then `accepted`, `exhausted`, `abandoned` or
`failed`.

Each round is a background task that **ends** by writing `awaiting_review` and
exiting. No coroutine ever blocks on a person, which is exactly why
`awaiting_review` survives a backend restart: the human's turn is the absence of
a running task.

`restore_sessions` fails any session caught in a working state. It does not
auto-resume — we cannot know whether the provider calls completed, and silently
re-billing them or double-counting the round cap is worse than failing.
`round_index` is incremented and persisted *before* any provider call, so a
crash loop cannot exceed the cap.

## Running the whole path locally

The hosted Qwen generator and Lean checker live on Modal. Without those
credentials, set `RESEARCH_LOCAL_LEAN=1` and the formalization step checks Lean
with the local pinned project instead (`LocalTools` in `ui/formalization.py`).
It runs the same `lake env lean` command the hosted checker runs and records the
same provenance shape, with `checker: "local"` added, so the contract gate
accepts it and the provenance is real rather than stubbed. Generation and
fidelity scoring stay hosted: use formal mode and paste the Lean. With no
fidelity model the status degrades to `review`, which keeps the alignment
acknowledgement required downstream.

```sh
elan toolchain install "$(cat problems/lean/lean-toolchain)"
(cd problems/lean && lake exe cache get Mathlib.Algebra.BigOperators.Group.Finset.Basic && lake build)
RESEARCH_LOCAL_LEAN=1 scripts/start_lab.sh
```

Then submit a statement the compiler cannot express — instance parameters
outside `Nat`, `Int`, `List Nat`, `List Int` — in formal mode. Preparation
answers 409 and the review panel appears.
`scripts/synthesis_fixture.py` holds a worked example using `List (Nat × Nat)`.

A session awaiting review is reachable at `/?synthesis=<id>`, so a backend
restart does not strand the reviewer mid-decision.

To drive the loop without the UI at all:

```sh
PYTHONPATH=src .venv/bin/python scripts/try_synthesis.py
```


## Evidence tier

| Value | Meaning |
| --- | --- |
| `lean_compiled` | `LeanFitnessFunction`. Every score carries a Lean kernel certificate. |
| `trusted_handwritten` | A registered, operator-written scorer from the built-in registry. |
| `lean_checked_synthesised` | This path. Lean checked, compiler could not express it, scorer model-written and human-accepted. |

Recorded in the scorer manifest (covered by the digest), in contract provenance,
and returned by `POST /api/contracts`. Results in the `lean_checked_synthesised`
tier must never be reported in the same table as the other two.

## Limitations to disclose

- **The human is the weakest link.** The panel puts the declared feasibility
  rules and objective derivation first and collapses the source, because
  reviewing a claim is a task a person can do and reading eighty lines of
  scoring code is not. That is a mitigation, not a guarantee.
- **Agreement is not correctness, and this build does not even measure
  agreement.** Differential execution of both candidates was cut for time, so
  the critic argues from reading rather than from measured disagreement. Two
  models sharing one misreading of the same statement is the common failure, not
  the rare one.
- **No degeneracy red team.** `judge-synthesis.md` calls it the most valuable
  check in the no-ground-truth case. It needs a frozen scorer and a short search,
  so it belongs after acceptance and before contract freeze. Not implemented.
- **Rounds 2 and 3 may be worse than round 1.** Both candidates are regenerated
  from scratch each round, so nothing guarantees monotone improvement. Every
  round's sources are retained, so re-accepting an earlier one could be added.
- **Per-case scoring costs a container launch**, multiplied by candidates ×
  cases. Comparable to the Lean path, but far more expensive than a registered
  host-side scorer. Measure before relying on it for a full run; batching the
  worker is the known fix and the adapter does not foreclose it.
- Lean checking establishes that a statement compiles, not that it expresses the
  user's intent. The alignment acknowledgement records a human judgement.

## Tests

| File | Covers |
| --- | --- |
| `tests/test_scorer_protocol.py` | wrapper verdicts, `parse_verdict`, the static gate. No Docker, no network. |
| `tests/test_scorer_synthesis.py` | two models and two framings, `tool_choice auto`, gate failures, critic fallbacks. Stubbed clients. |
| `tests/test_synthesis_adapter.py` | freeze, exact `Fraction` scoring, defect vs invalid, integrity, and `evaluate_case` through `asyncio.to_thread`. Docker-gated. |
| `tests/test_synthesis_session.py` | rounds, the cap, failing closed, restart semantics. |
| `tests/test_ui_synthesis.py` | the 409 offer, review conflicts, the attachment route, and the full accept-to-contract path. |
| `frontend/src/scorerReview.test.ts` | decision rules and the no-`innerHTML` structural guarantee. |
