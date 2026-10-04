# Fitness function synthesis and qualification

Status: proposed 4 October 2026, revised against `main` at `ee70270`. Not
accepted. Requires team review before implementation, and separate review before
any reported result depends on a synthesised fitness function. This document does
not change [shared-semantics.md](shared-semantics.md) or
[evolution.md](evolution.md).

## Problem

The hand-written known-problem step is now implemented for six registered
families; see [known-problems.md](known-problems.md) for sources, fixed instances
and qualification. The synthesis and qualification automation proposed below
remains unimplemented and deferred.

Scaling to a new problem family currently requires a teammate to hand-write a
`FitnessFunction`. That is the correct default and should stay the default for
anything we report. It does not cover two cases:

1. **A fitness function exists upstream but we have not written ours.** A
   benchmark fixes validity and the objective. Example: the AlphaEvolve math
   problems, each with a reference evaluator and a published benchmark constant.
2. **No fitness function exists.** The user has a problem and an informal idea of
   success. Nobody knows the correct scores, so there is no ground truth against
   which to check a candidate fitness function.

This document proposes synthesising the per-problem fitness function with a model
and qualifying it before the registry will admit it. The check set differs between
the two cases above, and the difference is stated explicitly below.

## What `main` already provides

`ee70270` did the structural work this proposal depended on. The following is
existing behaviour, not proposed:

- [fitness/base.py](../src/the_pigeon_holes/fitness/base.py) reduces the
  per-problem surface to two methods: `validate_contract(problem)` and
  `evaluate_case(case, output) -> CaseFitness`. `CaseFitness` carries validity,
  metrics (`int`, `float` or `Fraction`), an optional behavioural descriptor, a
  failure reason, and free-form evidence.
- [evaluation/production.py](../src/the_pigeon_holes/evaluation/production.py)
  (`SandboxCandidateEvaluator`, version `sandbox-fitness-v1`) owns everything
  generic: signature validation, container limits, per-case and per-candidate
  deadlines, cancellation, the `failure_stage` and `repairable` taxonomy, evidence
  recording, descriptor selection, and aggregation over `sum`, `mean`, `median`
  and `worst_case` including tie-breaker metrics. Exact rationals survive
  aggregation and are recorded as `aggregate_metrics_exact`.
- [fitness/registry.py](../src/the_pigeon_holes/fitness/registry.py) admits only
  operator-trusted functions. `resolve()` fails closed on an unknown
  `(id, version)` and on an implementation digest that does not match the
  contract.
- `ProblemContract.fitness_function` is a content-addressed
  `FitnessFunctionRef(id, version, implementation_sha256)`, frozen with the rest
  of the contract.

Three consequences for this proposal:

- The surface a model must write is already small and already has a protocol.
  There is no need to invent one.
- The registry is already the gate. Admission is an operator action, so "human
  sign-off" is mechanical rather than procedural.
- `implementation_sha256` already pins a specific implementation to a specific
  contract, which is exactly what a synthesised function needs.

## Proposal

Add one stage between Lean checking and contract freezing, plus two supporting
pieces:

```
1.  Natural-language specification
2.  Lean formalisation and hosted check                  (unchanged)
2.5 Fitness synthesis, qualification, registration       (new)
3.  ProblemContract frozen                               (unchanged shape)
4-8 Evolution, sandbox, scoring, archive, feedback       (unchanged)
```

1. **Synthesis.** Two independent model calls produce two candidate
   implementations from the checked Lean statement and the extracted interface.
2. **A sandboxed adapter.** A `FitnessFunction` implementation that runs
   synthesised code in a container instead of on the host.
3. **A qualification harness.** A fixed battery of checks that must pass before
   the operator registers the function.

The stage runs once per problem, before the loop. Two generations plus a
reference is roughly three model calls, negligible against a run, and it adds
nothing to per-candidate cost.

Synthesis is never implicit. A contract naming an unregistered function already
fails closed in `resolve()`; that behaviour must not be relaxed.

## What the model writes

The synthesised artifact is not a `FitnessFunction` class. It is a module
exposing two pure functions that the adapter calls:

```python
def validate(output, **case_inputs) -> str | None   # None when valid
def score(output, **case_inputs) -> dict            # metric name -> exact rational
def descriptor(output, **case_inputs) -> tuple[float, ...]   # optional
```

Everything else stays where `main` put it. The model does not choose the
aggregation, the tie-breakers, the deadlines, the container policy, the failure
taxonomy, or the repair decision. A subtle error in any of those corrupts the
search silently, and they are already written and tested. The model answers only
whether one output is valid and what its metric values are.

Metrics cross the container boundary as numerator/denominator string pairs, which
the adapter converts to `Fraction` before returning a `CaseFitness`. Exactness is
then preserved through aggregation by existing code.

## The sandboxed adapter

`SandboxCandidateEvaluator` calls `evaluate_case` on the host, via
`asyncio.to_thread`, and [base.py](../src/the_pigeon_holes/fitness/base.py)
documents implementations as trusted. Synthesised code cannot satisfy that
contract: on the host it would sit beside `runs/`, the SQLite store, and the
ignored `.env`.

The adapter is therefore a `FitnessFunction` whose `evaluate_case` ships the
synthesised module and one `(output, case_inputs)` pair to a container and parses
a JSON verdict. It runs in a container separate from the candidate's, so the
scoring code is never co-resident with the code being scored.

`run_candidate_async(source, entry_point, args, limits, image)` in
[container_runner.py](../src/the_pigeon_holes/execution/container_runner.py)
already has this shape and needs no new execution path.

Two details to settle:

- **`evaluate_case` is synchronous** in the protocol, and the adapter needs an
  async container call. Either the protocol gains an async variant, or the
  adapter runs its own event loop in the worker thread the evaluator already
  provides. The second keeps `main`'s interface unchanged and is preferred.
- **Digests need a file.** `source_sha256(__file__)` hashes a module on disk. A
  synthesised function must have its source persisted as a run artifact and
  hashed from there, so `implementation_sha256` identifies the exact text that
  was qualified.

## Qualification checks

These categories already exist as hand-written tests for the autocorrelation
function in
[test_autocorrelation_fitness.py](../tests/test_autocorrelation_fitness.py). The
harness generalises that file into a battery every synthesised function must pass.

| Check | Existing example | Needs ground truth |
| --- | --- | --- |
| Known answers | `test_exact_value_for_small_hand_case`, `test_constant_function_has_c1_two_for_every_length` | yes |
| Reference agreement | `test_exact_value_agrees_with_float_reference` | no |
| Malformed input rejection | `test_invalid_outputs_are_rejected`, `test_too_long_output_is_rejected` | no |
| Invariance and metamorphic | `test_scale_invariance`, `test_reversal_invariance`, `test_zero_padding_changes_only_through_n` | no |
| Determinism and pinned identity | `test_repeated_calls_are_identical`, `test_identity_and_version_are_pinned` | no |
| Descriptor sanity | `test_descriptors_are_deterministic_and_bounded` | no |
| Planted-bug detection | `test_planted_factor_bug_is_detected_by_known_answer` | no |
| Degraded-candidate ranking | not present | partial |
| Degeneracy red team | not present | no |

Planted-bug detection gates the harness rather than any one function: it measures
whether the battery has teeth. `test_fitness_registry.py` already covers the
admission side — content-addressed resolution, fail-closed on a changed
implementation, duplicate identity rejection, and aggregation direction.

Because `evaluate_case` is a pure function of `(case, output)`, the harness is a
pure comparison. It needs no run, no evolution loop, and no container when
comparing two host-side implementations.

## Two generations and their disagreement

Two implementations are synthesised independently from the same checked Lean
statement and frozen interface, with no visibility of each other. Both must pass
every ground-truth-free check. Selection then uses agreement with the reference
and with each other over a shared pool of `(case, output)` pairs, following
CodeT's dual-execution agreement.

Disagreement is a signal, not noise. Where one accepts an output the other
rejects, the disagreement localises an ambiguity in the specification. Those
cases are reported rather than settled by majority. A validity disagreement
blocks automatic qualification and escalates to a human.

Agreement does not establish correctness. Two models can share one misreading, so
neither the reference implementation nor the red-team pool may come from the
prompt that produced the two candidates.

## No fitness function: elicitation

Without ground truth, known-answer checks are unavailable and reference agreement
weakens, because the reference is synthesised from the same informal description.
The check set shifts rather than shrinks, and the degeneracy red team below
carries most of the weight.

The elicitation path reuses the existing composer flow, which already collects
problem, objective and constraints as prose
([Composer.tsx](../frontend/src/Composer.tsx)), formalises it through
`POST /api/formalizations`, and records an explicit alignment acknowledgement via
`alignment_reviewed` ([preparation.py](../src/the_pigeon_holes/ui/preparation.py),
[customResearch.ts](../frontend/src/customResearch.ts)).

[problems/autocorrelation/problem.txt](../problems/autocorrelation/problem.txt)
is the template for what elicitation must produce. It states the continuous
problem, the exact output convention, every feasibility rule, the metric, the
aggregation, the interface, the sandbox restriction, and an explicit list of what
is *not* claimed. Prose of that quality can be formalised and scored. A single
sentence naming an objective cannot. The elicitation UI exists to close that gap,
so its target is a structured statement of comparable completeness.

Required properties of the flow:

- **Round-trip through a reviewable artifact.** Prose produces a proposed
  structured objective; the user confirms or corrects that; only then is a
  function synthesised. A user can verify a short structured statement. Nobody
  can verify eighty lines of scoring code. The structured form is already the
  contract's target, since `extract_signature` yields
  `OptimisationGoal(MetricGoal(name, direction), aggregation, tie_breakers)` and
  `main` now supports four aggregations.
- **Ask about validity and the objective separately.** Informal descriptions
  state the objective and omit the feasibility rules. An approximate objective
  degrades search; wrong validity invalidates every result in the run. The
  validity half gates harder.
- **Ask what the user can actually answer.** Which transformations must not
  change the score, and what an obviously bad answer looks like. Neither needs
  known optimal values, and both feed the battery directly.
- **Surface disagreement as a question.** "Should duplicate points be allowed?"
  is answerable by the user and resolves the ambiguity at its source.

### Degeneracy red team

This replaces the known-answer check and is the most valuable check in this case.
A loosely specified objective is gamed by the search, not respected by it.
Maximising the smallest triangle area with no constraint on the region is
unbounded: separating the points without limit improves the score forever. The
reference Heilbronn evaluator normalises by convex-hull area specifically to
prevent this, and a function synthesised from one sentence of prose would
plausibly omit it.

Before the real run, spend a small bounded budget attacking the function: request
outputs that score well while violating intent, run a short search against it,
and show the highest-scoring result to the user. A user who rejects that output
has disproved the objective for the cost of seconds of compute, instead of a full
run and a false claim.

## Registration and gating

The registry is the gate, and `main` already enforces most of it.

- Qualification completes before the contract freezes.
- A failed battery means the function is not registered, so `resolve()` fails
  closed and the run cannot start. No partial admission.
- Validity disagreement between the two candidates blocks automatic
  qualification.
- Registration is an operator action through `RESEARCH_FITNESS_REGISTRY`,
  consistent with the rule in
  [team-practices.md](../context/team-practices.md) that fitness and evaluator
  changes are agreed and versioned separately.
- The qualification report, both synthesised sources, every check result, and the
  agreement score belong in run evidence so `scripts/export_run.py` carries them.
- Add an explicit `evidence_tier` (`lean_checked` or `prose_reviewed`) to the
  contract, the UI, and exports. Results from a hand-written function and from a
  synthesised one must not be reported in one undifferentiated table.

## Couplings to resolve before implementation

- **Behavioural descriptors.** `SandboxCandidateEvaluator` takes the first
  non-`None` descriptor across cases and the engine uses it for island cells. A
  synthesised function that returns no descriptor silently collapses diversity to
  one niche, so either `descriptor` is mandatory or the engine needs a documented
  fallback deriving cells from the metric.
- **Failure reasons.** `CaseFitness` requires a non-empty `failure_reason` when
  invalid, and the evaluator maps that to `invalid_output`, which is in
  `REPAIRABLE_STAGES`. Synthesised validation must return a reason string, not
  raise an arbitrary exception, or repair routing degrades.
- **Metric names must match the goal.** The evaluator raises
  `RuntimeError("fitness function omitted configured metric ...")` when a metric
  named in `OptimisationGoal` is missing. The battery must check every configured
  metric and tie-breaker, not just the primary.
- **Container dependencies.** Several families need numpy or scipy, and
  `problem.txt` currently promises the standard library only. The worker image is
  bare Python pinned by digest. Any added dependency changes the sandbox surface
  and must be versioned with the fitness function.

## First experiment

Autocorrelation is the only family with a trusted function, which makes the first
calibration cheap and decisive. Synthesise a fitness function from the
autocorrelation Lean statement and
[problem.txt](../problems/autocorrelation/problem.txt), then compare it against
`AutocorrelationFitnessFunction` on `(case, output)` pairs drawn from candidates
already stored under `runs/`.

The new protocol makes this nearly free: both implementations are pure functions
of `(case, output)`, so the comparison needs no run, no containers, and no model
calls beyond synthesis. Correct validity verdicts and exact metrics are known for
those stored candidates.

Any disagreement means the harness is not ready. Agreement on stored candidates
plus a passed planted-bug check gives a measured basis for applying it to a new
family.

This is also the defensible form of the research claim: not that the system
synthesises correct fitness functions, but that a synthesised one was measured
against a trusted one on recorded candidates, and that the battery detects
injected faults at a stated rate.

## Limitations to disclose

- A synthesised fitness function is weaker evidence than a hand-written one, and
  far weaker than a proof. Agreement between two synthesised functions is not
  correctness.
- Lean checking establishes that a statement compiles, not that it expresses the
  user's intent. The alignment acknowledgement records a human judgement, not a
  verified property.
- A prose-sourced objective carries the additional risk that the search optimises
  the stated criterion rather than the intended one. The red team reduces this
  risk and does not eliminate it.
- No literature was found covering fitness synthesis for open-ended optimisation
  problems. The components below are adapted from adjacent work, so the
  composition is untested.

## Open decisions

1. Whether prose-only runs are permitted at all, or whether every run requires a
   checked Lean statement with prose used only to produce it. Recommendation: the
   latter for anything reported as a result, with prose-only available and
   clearly labelled by `evidence_tier`.
2. Whether the two generations use one model with different prompts or two
   different models. Different models give more independence at the cost of
   reproducibility and spend.
3. Whether the sandboxed adapter is accepted at all, or whether synthesised
   functions must be reviewed into hand-written host-side implementations before
   registration. The second is slower but keeps `FitnessFunction` uniformly
   trusted, which is a real simplification.

## References

Adjacent work, with the specific borrowed idea:

- CodeT, [arXiv:2207.10397](https://arxiv.org/abs/2207.10397). Dual-execution
  agreement between generated tests and candidate programs. Source of the
  two-generation selection rule, and of the finding that a single count is a
  weaker ranking signal than agreement.
- ALGO, [arXiv:2305.14591](https://arxiv.org/abs/2305.14591). Model-generated
  slow reference solutions used as oracles. Source of the reference-agreement
  check on small instances.
- REFINE, [arXiv:2508.02827](https://arxiv.org/abs/2508.02827). Synthesising
  progressively degraded artifacts to test whether an evaluator ranks them
  correctly. Source of the degraded-candidate check.
- Who Validates the Validators?,
  [arXiv:2404.12272](https://arxiv.org/abs/2404.12272). Aligning model-assisted
  evaluation with human judgement on examples. Source of the elicitation design
  for the no-ground-truth case.
- AlphaEvolve, [arXiv:2506.13131](https://arxiv.org/abs/2506.13131). Assumes a
  human-supplied `evaluate` function, which is the gap this proposal addresses.
