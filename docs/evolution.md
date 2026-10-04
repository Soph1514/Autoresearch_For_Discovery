# Evolution loop

## Status and precedence

This document is the source of truth for evolution-specific behavior. It
refines the evolution and Python-implementation stages in [agents.md](../context/agents.md)
without changing the rest of the accepted pipeline.

The evolutionary unit is an executable program candidate. One LLM generation
produces a falsifiable hypothesis and a complete implementation of the required
`solve(...)` function together. There is no separate idea-to-code translation
call.

## Scope

Evolution decides where to search next, which prior programs to use, which
failures are worth repairing, and which distinct results deserve preservation.
It does not establish mathematical validity, calculate trusted objective
metrics, sandbox generated code, or change the problem specification or
fitness function or evaluator.

The sub-loop uses injected generator and evaluator protocols and in-memory search
state. Production adapters now include Anthropic generation, a generic
Docker-backed evaluator, and a registered autocorrelation fitness function; the
UI persists evidence and outcomes in SQLite.

## Input

Evolution receives the immutable `ProblemContract`, containing:

- the natural-language specification;
- the Lean formalization;
- the complete versioned Python interface, including supporting types;
- a seed program;
- an immutable evaluation suite hidden from generation prompts;
- the `OptimisationGoal`;
- per-case and per-candidate resource limits; and
- a content-addressed reference to a required trusted fitness function.

Lean expresses the formal intent. It does not by itself prove that generated
Python implements that intent. The deterministic fitness function remains
authoritative unless a returned proof or certificate is checked by a trusted
formal checker.

## Program candidates

Every generated candidate records:

- its generation and island;
- its operator, parents, and non-parent inspirations;
- a hypothesis;
- a predicted measurable effect;
- a falsification condition;
- mechanism tags; and
- the complete source code implementing `solve(...)`.

Generated candidates also retain their request ID, rendered generation prompt,
and provider-reported token use so their provenance and cost remain auditable.

Evolution assigns candidate and lineage identifiers. The LLM does not.
Candidates are immutable; repairs and mutations create descendants rather than
overwriting earlier attempts.

## Evidence and archives

The loop maintains three logical stores:

1. **Evidence history:** every generated candidate, generation failure, and
   evaluation.
2. **Elite archive:** verified-valid local elites and the separately preserved
   global best.
3. **Novelty archive:** useful stepping stones that are materially different,
   including explicitly quarantined invalid candidates.

The in-memory novelty archive is size-bounded and retains the highest-scoring
entries when full. Evidence history remains complete even when an entry leaves
the novelty working set.

Invalid novelty candidates must have recorded failure evidence and be judged
repairable or informative. They may be repair targets, labelled inspirations,
or negative examples. They may not be elites, ordinary crossover parents,
island founders, the global best, or returned solutions. Unsafe candidates stay
in evidence history only.

## Islands and local elites

The loop starts with four active islands and permits growth to a configurable
maximum, initially eight. Each island preserves up to four behavioral-cell
representatives and one active local elite (the best representative). Candidates
compete within their cell; capacity pressure evicts the weakest representative.
The global best is stored independently so island lifecycle changes cannot lose it.

A valid candidate may found a new island when it is sufficiently novel and is
either Pareto-nondominated on objective quality and novelty or ranks in the top
half of valid candidates while exceeding the spawn-novelty threshold. A new
island receives a protected incubation allocation.

Stagnant or capacity-displaced islands may become dormant. Their history and
elites are preserved. The initial implementation supports spawning and
dormancy but defers automatic merging until stronger behavioral descriptors
exist.

Behavioral descriptors are optional. When a fitness function supplies a stable
descriptor, evolution uses it for novelty and island spawning. When absent,
novelty falls back to mechanism tags, source structure, lineage, and failure
signatures. No universal normalization contract is imposed in the first
implementation.

## Generation policy

Each generation produces up to two offspring per active island, capped by the
configured batch size and remaining token budget. Every active island receives
one guaranteed request when affordable; remaining requests are allocated using
incubation and stagnation state.

Initial operator weights are:

- 45% mutate a parent selected from the local pool;
- 15% crossover valid, distant candidates;
- 10% develop a valid novelty candidate;
- 15% repair an invalid novelty candidate; and
- 15% generate a fresh restart.

Unavailable operator weight is redistributed among eligible operators.
Ordinary mutation uses a seeded tournament over the local pool (default size two).
Crossover excludes the first parent from the second tournament and falls back to
the distance rule when needed. Both use valid candidates only.
Repair directly targets a repairable invalid novelty candidate. A restart has
no program parent. Up to two archive entries may be supplied as inspirations,
with their validity and known failures clearly labelled.

The LLM API is a semantic variation operator. Diversity comes primarily from
operator choice, mutation strength, parent and inspiration selection, search
directions, prompt variants, and fresh restarts. Token-level negative KL is not
used.

## Novelty

Novelty controls search allocation and preservation; it never overrides
invalidity or trusted objective performance. The first implementation uses:

- exact and normalized-AST duplicate detection;
- source-structure distance;
- mechanism-tag distance;
- direct-lineage separation;
- optional behavioral distance; and
- failure-signature differences for invalid candidates.

LLM novelty judgments, code embeddings, and learned descriptors are deferred.

## Evaluation and update

Evolution performs cheap syntax, exact-signature, and duplicate checks. The
injected evaluator is responsible for sandbox execution, resource limits,
suite aggregation, and returning evaluations. It delegates problem-specific
validity, objective metrics, exact evidence, and behavioral descriptors to the
trusted fitness function referenced by the contract.

The evolution-facing evaluator interface is intentionally opaque: it returns one trusted
evaluation per candidate. Smoke, discovery, confirmation, and holdout stages
may be internal to that evaluator and will be exposed only after their shared
contracts are designed.

After a batch completes, results are committed in stable candidate-ID order.
Invalid candidates never become elites. Valid candidates compete locally under
the lexicographic `OptimisationGoal`: the primary metric followed by configured
tie-breakers. Novel candidates may enter novelty memory or spawn an island.
Only then is the next generation planned from the updated snapshot.

## Stopping and budgets

Evolution has a separate run budget from evaluation resource limits. At
least one of maximum elapsed time or maximum LLM tokens must be configured. The
loop stops when:

- elapsed monotonic wall time reaches the limit;
- reported input plus output token use reaches the limit; or
- the remaining token budget cannot afford another request.

If an entire dispatched batch returns only generation errors, the loop also
returns a `generation_failed` outcome rather than retrying forever without
producing evidence-bearing candidates. Provider adapters should handle
transient retries before returning such errors.

The time limit covers active evolution time, including seed evaluation and
candidate execution, but excludes time fully paused at a batch boundary.
In-flight draining before that boundary still counts. Token use covers every
evolution-related LLM call.
Generation and optional advisory critic calls share provider token admission in
the live CLI. Reported critic usage, including malformed replies, is charged to
the loop. Future formatting repairs and reflections must use the same budget.

Before dispatch, each request reserves a configured conservative token ceiling.
Reservations are replaced with actual provider-reported use afterward. If an
API call exceeds its reservation, its completed result is retained and the loop
stops scheduling further work.

The optional critic assesses valid candidates only, is cached by source fingerprint,
and is bounded by `max_critic_calls` and the active-time deadline. Its notes are
labelled advisory in later prompts and never affect validity or elite ranking.
Separate reflection calls and measured critic-quality monitoring remain deferred.

## Initial component contacts

Evolution depends on two batch-oriented protocols:

- `ProgramGenerator`, which turns generation requests into candidate drafts and
  reports token use; and
- `CandidateEvaluator`, which returns trusted deterministic evaluations.

It also accepts an optional synchronous `EvolutionObserver` for lifecycle
evidence and an async next-generation checkpoint for orchestration controls.
The checkpoint is outside both adapters, so replacing the demo generator does
not change pause/resume semantics.

`AnthropicProgramGenerator` is the first production generator adapter. It uses
schema-constrained candidate submission and bounded concurrency, per-attempt
timeouts, and retries; orchestration supplies its model/configuration. The
custom-run bridge constructs adapters and calls the loop. Evidence storage and
Docker execution are implemented. Optimizer resumption after restart, formal
certificate checking and staged confirmation remain future work.

## Non-negotiable invariants

- The problem specification, Lean formalization, optimization goal, suite, and
  content-addressed fitness function stay fixed during a run.
- Generated programs cannot modify the evaluator, fitness function, or benchmark data.
- Invalid candidates never become elites or returned solutions.
- LLM criticism cannot override deterministic validity or measured fitness.
- One active elite is preserved per island and the global best is preserved
  separately.
- Island retirement never deletes evidence.
- Novelty must reflect code, mechanism, lineage, failure, or measured behavior,
  not different wording alone.
- Batch results are committed deterministically after generation and evaluation
  complete.
- Prompts, responses, token use, lineage, scores, costs, and failures remain
  attributable to their candidates.

## Initial defaults

- minimum active islands: 4;
- maximum active islands: 8;
- local pool capacity: 4 behavioral cells, with one elite;
- tournament size: 2;
- offspring per island: 2;
- maximum generation batch: 16;
- maximum novelty working set: 128;
- new-island incubation: 5 evaluations;
- island stagnation threshold: 8 evaluations; and
- maximum new islands per generation: 1.

These are configurable starting points, not benchmark-validated constants.
