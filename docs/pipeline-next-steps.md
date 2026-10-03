# Remaining pipeline work

The UI now handles attachments, Qwen generation, Lean checking/repair and fidelity
review. The evolution demo runs separately with a prepared Pigou contract.
See [current integration](ui-integration-status.md), [shared semantics](shared-semantics.md)
and the [event contract](api-events.md) for implemented behavior.

The contract builder, complete versioned interface, immutable evaluation suite,
Anthropic program generator and native evolution events are implemented. The
remaining handoff is:

1. **Prepare custom contracts.** Carry checked Lean and toolchain provenance through
   extraction; bind a seed, fixed evaluation suite and evaluator version with
   `build_problem_contract`. Validate the seed before starting evolution. Run
   generated helper code only in the protected environment.
2. **Implement the protected evaluator.** Isolate candidate execution, enforce
   time/memory limits and prevent changes to the judge or benchmark data. Return
   explicit crash/timeout/invalid evidence; only valid finite metrics qualify for elites.
3. **Connect production orchestration.** Wire accepted preparation into
   `EvolutionLoop.run(contract)` with production adapters. Expose progress and
   failures without substituting a demo. Preserve cancellation and paused-time
   accounting; enforce deadlines within provider/evaluator calls.
4. **Persist and secure runs.** Store contracts, candidates, evidence, events and
   usage; define restart recovery and add authentication before public hosting.
5. **Verify one complete run.** Exercise custom input through preparation and
   evolution, including rejection and cancellation. Record reproducible commands,
   versions, results and measured costs. Lean specification checking alone does
   not prove the generated Python correct.
