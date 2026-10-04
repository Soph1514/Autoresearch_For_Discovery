# Remaining pipeline work

Reconciled on 2026-10-04 with main `e366466`, custom-run integration `7e26e8a`,
and evaluator branch `origin/eo_loop` at `36fadc0`.

## Done

- Lean generation/checking/repair, fidelity review, server-recorded check provenance,
  immutable contract preparation, and both custom-run UI entry points.
- Built-in `autocorrelation-exact-v1` evaluator: Docker execution, exact host-side
  scoring, contract admission, per-case and suite timeouts, memory limits, bounded
  output, and cancellation that removes the candidate container.
- Real generator/evaluator orchestration, seed validation, island pools and
  tournament parent selection, ordered UI events, and evidence downloads.
- Optional advisory critic in the CLI. Generator and critic share token admission;
  critic usage is charged even when its response is malformed. Critic deadlines
  retain completed numerical evidence. The UI can render critic events, but does
  not enable critic calls by default.
- SQLite history and replay, restart interruption handling, and optional API auth.
- Local worker built and real Docker tests run. A scripted smoke run also exercises
  evolution and durable evidence; it is not an LLM benchmark or a Lean proof.

## Local end-to-end demo completed (4 October 2026)

The checker was redeployed, an explicit continuous/finite Sidon specification was
checked, and the hosted preparation → custom UI → Docker → critic → archive path
was exercised with live Anthropic generation. The natural-language Qwen attempt
needed a reviewed replacement; this is disclosed. Exact integer witnesses,
lineage, rejected attempts and held-out checks are exported. See
[demo verification](demo-verification.md) for measured results and replay steps.

## Remaining research/submission work

4. **Repair the remaining evidence gaps.** Rerun the disputed Ireland–Rosen Lean
   benchmark result; historical timings are retained but its verdict is unproven.
   Evaluate fidelity on held-out examples—the existing ten-example comparison
   includes training examples.
5. **Record the <=4-minute video and prepare submission.** Show measured improvement
   over a baseline, distinguish numerical validation from formal proof, and include
   reproducible setup, repository URL, costs, limitations and video link.

## Follow-up limitations to resolve or disclose

- The evaluator supports only the autocorrelation family, not arbitrary uploaded
  problems. Other families need their own trusted versioned judges and adapters.
- `ResourceLimits.max_iterations` is not independently enforced by this worker.
  Wall-clock and memory limits are enforced; do not claim an instruction/iteration cap.
- Exact rational scores become floats at the evolution interface. The CLI rechecks
  the final output exactly, but near-tie ordering remains float-based.
- Host-side exact scoring runs in a thread. Cancellation stops container work and
  waiting on scoring, but cannot interrupt an already-running host arithmetic job.
- Critic quality is unmeasured; keep it advisory. Do not use its rating to override
  validity or measured rankings. Duplicate programs still use `static_validation`.
- The API is a single-process lab service with optional shared authentication,
  not per-user isolation or a multi-worker scheduler. Restart preserves evidence
  and marks interruptions; it does not resume the optimizer automatically.

## Evaluator setup and extension

```sh
docker build -t the-pigeon-holes/candidate-worker:v1 docker/worker
```

The built-in factory is `the_pigeon_holes.evaluation.production:create_evaluator`;
no `RESEARCH_EVALUATOR_FACTORY` setting is needed for autocorrelation. It rejects
unsupported evaluator versions, interfaces, metrics, aggregation and case sizes.
Docker must be reachable and the image available. Each evaluator resolves the
worker tag to an immutable local image ID, which is saved in run evidence.

For another family, set `RESEARCH_EVALUATOR_FACTORY=your_module:create_evaluator`.
The synchronous trusted factory receives a frozen `ProblemContract` and returns
an object implementing `async evaluate(candidates, problem)`. Client requests
cannot choose Python modules. The adapter must return one `CandidateEvaluation`
per candidate and honor cancellation and contract limits; invalid seeds stop
before generation. Never substitute the routing demo for an unavailable evaluator.

## Reproducible checks

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q
cd frontend
npm test
npm run build
```

Docker tests skip if Docker/image preflight fails. Tests make no live model calls.
For a live numerical search (the contract's Lean remains a placeholder):

```sh
PYTHONPATH=src .venv/bin/python scripts/run_autocorrelation.py \
  --model "$RESEARCH_MODEL" --n 64 --max-tokens 32768 --max-minutes 5 \
  --max-critic-calls 0 --seed 0
```

Set `ANTHROPIC_API_KEY` before running. Increase critic calls only when testing its
advisory value. Provider token counts are estimates; ambiguous in-flight billing
can remain unknown. Preparation calls are outside the evolution token budget.
