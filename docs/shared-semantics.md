# Shared pipeline semantics

Status: accepted 2026-10-03. This document defines the boundaries shared by
formalization, contract preparation, evolution, evaluation, and orchestration.
Component ownership is fixed here; assignment to named teammates remains a
team coordination decision.

## Component ownership

- **Formalization** owns Lean source and Lean check artifacts.
- **Contract preparation** owns interface extraction, structural validation,
  immutable evaluation-suite preparation, and rejection diagnostics.
- **Evolution** owns search allocation, variation requests, lineage, novelty,
  and elite policy. It does not execute candidate code or inspect hidden cases.
- **Evaluation** owns sandbox execution, suite cases, deterministic validity,
  metric calculation, aggregation, and behavioral evidence.
- **API/UI orchestration** owns run identity, lifecycle controls, and event
  presentation. It does not choose elites or reinterpret validity.

## Problem family and evaluation suite

A `ProblemContract` describes one general problem family and binds one or more
immutable evaluation cases. Each call to `solve(...)` receives one case. The
evaluator maps a candidate over the suite and applies
`OptimisationGoal.aggregation` to produce each reported metric.

The generation port receives rendered requests containing the general problem,
Lean context, complete Python interface, objective, and selected evolutionary
evidence. It never receives evaluation case values, expected answers, or judge
internals. The evaluation port receives the complete contract.

The suite ID, cases, interface version, evaluator version, specification, and
goal are fixed for a run. Stored case data is recursively immutable. An
evaluator must request an isolated materialized copy before sandbox execution.

## Limits and run controls

- `ResourceLimits.case_time_seconds`, `memory_mb`, and `max_iterations` apply
  to one sandboxed `solve(...)` case.
- `ResourceLimits.candidate_time_seconds` caps the complete suite evaluation
  for one candidate.
- `EvolutionLimits.max_time_seconds` caps active run time; time spent fully
  paused at a batch boundary is excluded. In-flight draining before the pause
  boundary counts.
- `EvolutionLimits.max_tokens` covers all evolution-related provider usage.
- Provider concurrency, per-call timeout, and retry limits belong to provider
  adapters. Exhausted calls return explicit generation failures with usage.

Pause stops new scheduling at a batch boundary and retains completed evidence.
Stop requests cancel in-flight adapter work; a partially completed batch is not
committed. Adapters must propagate cancellation rather than convert it into a
valid result. The loop enforces active-time deadlines around generation and evaluation awaits.
Adapters must honor cancellation to terminate actual worker execution. The bridge
uses an active-time clock.

## Meaning of checked Lean

“Checked Lean” means that the recorded source was accepted by an actual Lean
invocation. Its artifact must include the source or content hash, Lean and
toolchain versions, dependency versions, command outcome, and diagnostics.
Successful Python parsing or interface extraction is not Lean verification.
Producing and persisting this artifact is formalization work; the contract
currently carries Lean source but must not label it checked without the
artifact.

## Complete Python interface

The contract preserves a versioned interface containing ordered parameter
names and types, return type, exact `solve(...)` signature, and supporting type
definitions. Preparation parses supporting definitions for structural input
validation but never executes them. Future evaluators may load them only inside
the protected candidate execution environment.

Metric names must be nonempty and unique, directions and aggregation must be
known, all limits must be positive and coherent, the seed must implement the
exact synchronous signature, and every evaluation case must match the complete
parameter and structured-type schema before evolution starts.
