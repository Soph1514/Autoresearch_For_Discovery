# Sandbox evaluator and autocorrelation fitness: implemented behavior

Merged from `origin/eo_loop` (`36fadc0`) into the custom-research integration on
2026-10-04. The authoritative remaining-work list is
[pipeline-next-steps.md](pipeline-next-steps.md).

## Implemented

- `problems/autocorrelation/fitness.py`: exact integer validation and rational `c1` scoring.
  Candidates return nonnegative integers representing `q_i / 2**40`. Length must
  be between 2 and 4096; bools/floats, all-zero and tiny-integral outputs fail.
  Its registered identity is `autocorrelation` version `exact-v1`, with a source
  digest that changes when its implementation changes.
- `fitness/registry.py`: server-controlled registry. Only registered functions
  can be referenced by a new problem contract; API clients cannot supply code or
  Python import paths.
- `evaluation/production.py`: generic sandbox `CandidateEvaluator`.
  Contract compatibility is checked by the selected registered fitness function.
  Autocorrelation requires `solve(n: int) -> list[int]` and mean `c1`
  minimization. Other supported families and objectives are listed in
  [known-problems.md](known-problems.md). Unsupported contracts fail before
  execution. Valid output must pass every suite case.
- `execution/container_runner.py`: bounded Docker preflight; worker tags resolved
  to local immutable image IDs; async candidate execution; network disabled,
  read-only filesystem, memory/swap cap, CPU/PID limits, unprivileged user and
  dropped capabilities. Stdout and stderr are each capped at 1 MB while streaming.
  Per-case and candidate-suite deadlines are enforced. Stop waits for container
  removal. A failed/timed-out cleanup is surfaced rather than silently ignored.
- `docker/worker/worker.py`: candidate module loading and `solve` run only inside
  the worker. Normal prints from both stages are discarded. No fitness code or
  other suite cases are passed to the worker.
- `evolution/engine.py`: bounded per-island behavioral-cell pools, one best
  representative per cell, seeded tournaments for parent selection, and separately
  retained island/global elites. Fractional descriptors are preserved rather
  than truncated to integer cells.
- `llm/critic.py`: optional valid-candidate-only advisory notes. It never changes
  validity, scores or elite decisions. The live CLI shares prompt/output token
  reservations between generator and critic; reported critic usage is counted
  even for malformed replies. Active-time deadlines also cover critic calls.
- `ui/bridge.py` and frontend: critic events persist, replay and render correctly;
  snapshots from before the merge may omit assessments. Custom UI runs currently
  leave the critic disabled. Docker factory wiring, source/evaluator evidence and
  worker image identity are persisted alongside run data.

## Setup and live command

```sh
docker build -t the-pigeon-holes/candidate-worker:v1 docker/worker
PYTHONPATH=src .venv/bin/python scripts/run_autocorrelation.py \
  --model "$RESEARCH_MODEL" --n 64 --max-tokens 32768 --max-minutes 5 \
  --max-critic-calls 0 --seed 0
```

Set `ANTHROPIC_API_KEY` and choose `RESEARCH_MODEL` first. The CLI saves attempts
and a summary under `runs/`, then reruns the best candidate for an exact-score
check. A numerical result does not imply Lean verification: the CLI contract
contains a clearly labelled Lean placeholder. The custom UI retains its genuine
checked-artifact requirement. The built-in UI factory needs no environment override;
other families can provide an operator-installed registry through
`RESEARCH_FITNESS_REGISTRY=module:create_registry`.

## Verification during reconciliation

- The worker image was built locally and the Docker-backed tests ran, without
  skips for missing Docker/image. They cover seed score, rejected outputs, crashes,
  case/suite timeouts, noisy stdout, streaming overflow and cancellation cleanup.
- Tests cover factory admission, shared token budgeting, critic deadlines/usage,
  pool selection, event replay, API persistence and restart behavior.
- A scripted 17-candidate run completed through the evaluator and persisted its
  evidence. All candidates were valid; the constant seed remained best at `c1=2`.
  This smoke run made no LLM calls and is not evidence of research improvement.
- A separate known inverse-square-root fixture verifies selection and persistence
  of a measured improvement over the constant seed. It is a test fixture, not a
  discovered result. Frontend tests and production build also pass.

Run checks with `PYTHONPATH=src .venv/bin/python -m pytest -q` and, in `frontend`,
`npm test` and `npm run build`. Tests do not make live model calls.

## Remaining limitations

1. Deploy checker provenance, formalize/review the actual autocorrelation problem,
   and verify a live hosted-preparation-to-Docker run.
2. Enforce or explicitly redesign `max_iterations`; this worker currently enforces
   time and memory but has no independent iteration counter.
3. Address float-based near-tie ordering in the engine. The fitness function computes exact
   fractions, but `CandidateEvaluation.metrics` exposes floats.
4. Bound/interrupt host arithmetic independently. Scoring runs in a host thread;
   cancelling its await cannot stop an arithmetic job already in progress.
5. Measure critic usefulness before enabling any influence beyond advisory prompts.
   Duplicate sources still share the `static_validation` failure stage.
6. Treat Docker isolation as a development execution boundary, not a formal
   security guarantee. Public multi-user service hardening is separate work.

Formal confirmation and certificates remain follow-up work; adding periodic Lean
rechecks is not a new requirement of the agreed MVP.
