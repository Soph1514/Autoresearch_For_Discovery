# Remaining pipeline work

Reconciled against main `e366466` and the custom-run integration in this branch.

Implemented: server-recorded formalizations and checker provenance, immutable
contract preparation, a custom-run UI, injected evaluator wiring, seed admission,
Anthropic generation with prompt/output token reservations, active-call deadlines,
SQLite artifacts and replay, restart interruption handling, evidence download, and
optional shared-password authentication. See [integration](ui-integration-status.md).

1. **Connect the incoming protected evaluator.** Implement `CandidateEvaluator`
   and the factory described below. Enforce case/candidate time, memory and
   iteration limits inside the isolated worker, protect judge and suite data,
   and return explicit crash/timeout/invalid results. Propagate cancellation to
   remote work. Reject unsupported evaluator versions and problem/metric contracts.
2. **Deploy the checker update.** Its response now records source hash, actual
   Lean/toolchain versions, Mathlib commit, dependency manifest, command outcome
   and diagnostics. Older checker deployments can still prepare Lean for review,
   but cannot create a custom contract until rechecked with this provenance.
3. **Run the live integration benchmark.** Supply a known seed and fixed suite,
   connect the evaluator and model, then exercise successful search, invalid seed,
   rejection, pause/resume, cancellation and restart recovery. Download evidence.
   The automated integration checks use injected ports; they do not establish that
   hosted services or sandbox execution work together.
4. **Recheck benchmark evidence.** The committed Ireland–Rosen result contained
   opposing verification verdicts in merge-conflict markers. It is now explicitly
   `not_proven` pending rerun; historical timing/cost fields remain. No local Lean
   installation was available during reconciliation. The separate ten-example
   fidelity comparison includes training examples and is not held-out evidence.
5. **Finish the presentation and submission.** Record the <=4-minute video only
   once the live run provides genuine algorithm-improvement evidence. Include
   setup, benchmark versions, costs, limitations, repository and video links.

## Evaluator handoff

Set `RESEARCH_EVALUATOR_FACTORY=your_module:create_evaluator`. This is trusted
server configuration, never a client-supplied Python import. The synchronous
factory receives the frozen `ProblemContract` and returns an object with:

```python
async def evaluate(self, candidates, problem):
    # Run candidates in the protected environment; never in the API process.
    # Return one CandidateEvaluation for every candidate.id, including failures.
    ...
```

The factory must reject contracts it cannot judge, including unsupported
`evaluator_version`, interface, suite or metrics. Generated helper definitions
are untrusted too. Valid results must pass every suite case and contain finite
values for the primary metric and all tie-breakers; the evolution loop enforces
these result-shape requirements. The first evaluation is the seed. A rejected
seed ends the run before generation. No evaluator is substituted when unavailable.

Whole-run deadlines cancel adapter awaits, but actual worker termination depends
on the evaluator honoring cancellation. The generator counts prompts and reserves
maximum output before provider calls, retaining reservations on ambiguous failure.
Token-count estimates may differ from provider billing; cancelled in-flight usage
can remain unknown. Preparation calls are outside the evolution token budget.

## Reproducible local checks

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q
cd frontend
npm test
npm run build
```

These tests make no live model calls. Live Lean benchmark verification additionally
requires the pinned Lean/Mathlib setup described in the root README.
