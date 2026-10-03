# Stage 0 evolution loop with LLM critic: what was built

Status: implemented locally, not committed, 2026-10-04. Scope: pipeline gap 4 (production evaluator) and the parts of gap 5 and gap 7 needed for a first search. Problem: `first_autocorr_ineq`. Lean confirmation (stage 1) is future work.

Related: [pipeline-next-steps.md](pipeline-next-steps.md), [evolution.md](evolution.md), [shared-semantics.md](shared-semantics.md).

## Design in one paragraph

Stage 0 decides everything that changes the search: validity, scores, elites, and parents. Stage 0 is a container run of the candidate followed by an exact judge on the host. An LLM critic runs after stage 0 on valid candidates only. Its output is advisory: it goes into later prompts and is labelled as such. It never affects validity, archive cells, or elites. Lean confirmation is not in the loop; it will become a periodic audit later.

## Principles

1. The gate never accepts an invalid candidate. Incomplete checks only cost volume.
2. The cost of a check matches the reversibility of its decision. Search decisions use cheap, sound checks.
3. The evaluator version and metric are fixed per run and recorded with every result.
4. LLM judgment orders and annotates work. It never gates validity or elites.
5. Every attempt is logged, including rejected ones.

## What exists now

### Exact judge (no floating point)

- `src/the_pigeon_holes/judging/autocorrelation.py`
  - Candidates return integers `q_i` meaning `q_i / 2**40` on `n` equal cells of `[-1/4, 1/4]`.
  - Validity: sequence of Python ints (bools rejected), length in `[2, 4096]`, non-negative, not all zero, integral squared at least `1e-8`.
  - Objective: `C1 = 2n · max(conv) / S²` with `Fraction`, where `conv[k] = Σ q_i q_{k-i}` and `S = Σ q_i`. The scale factors cancel exactly.
  - Comparison to the published bound uses an exact `Fraction` of the float literal. That bound is a published value, not a certified one.
  - Descriptor cell: `(min(int(support · 4), 3), min(peaks, 8))`, where support is the fraction of nonzero cells and peaks counts strict local maxima of the autoconvolution.
  - `JUDGE_VERSION = "autocorrelation-exact-v1"`.
- `src/the_pigeon_holes/judging/base.py`: `Judge` protocol (version and validate).
- `src/the_pigeon_holes/judging/autocorrelation_problem.py`: `autocorrelation_contract(n=600)`. One fixed case `{"n": n}`, entry point `solve(n: int) -> list[int]`, primary metric `c1` (minimise), seed `[2**40] * n` (C1 = 2). The natural-language spec states the 2⁻⁴⁰ unit convention. The Lean statement is a placeholder.

### Container execution

- `docker/worker/Dockerfile`: base image pinned by digest, `python@sha256:bb29…2e81` (python:3.13-slim). Runs in isolated mode.
- `docker/worker/worker.py`: reads one JSON request on stdin, runs `solve(**args)` with stdout redirected, and prints a JSON envelope. Catches `BaseException`, including `SystemExit`.
- Image built locally as `the-pigeon-holes/candidate-worker:v1`.
- `src/the_pigeon_holes/execution/container_runner.py`
  - `preflight()` checks the daemon and the image, and raises a diagnostic if either is missing. There is no silent fallback.
  - `run_arguments()` builds the `docker run` flags: `--network none`, `--read-only`, tmpfs `/tmp`, `--memory` and `--memory-swap` equal, `--cpus`, `--pids-limit 64`, `--user 65534:65534`, `--cap-drop ALL`, `--security-opt no-new-privileges`, `--rm`.
  - `run_candidate()` enforces a host-side wall-clock timeout (kills the named container), caps stdout at 1 MB, maps exit 137 to `memory`, and returns a structured result.
- Failure stages: `static_validation`, `crash`, `timeout`, `memory`, `invalid_output`.

### Stage 0 evaluator

- `src/the_pigeon_holes/evaluation/production.py`: `AutocorrelationEvaluator` implements `CandidateEvaluator`.
  - Checks the contract's `evaluator_version` against `JUDGE_VERSION`.
  - Static signature check via the existing `validate_source_signature`.
  - Runs each case in a container, then checks the output length against the case's `n`, runs the exact judge, and reports `c1` (mean over cases), the descriptor cell, and pass counts.
  - Runs up to `max_workers` candidates concurrently, in threads.

### Engine: island pools, cells, tournaments

- `evolution/models.py`
  - `EvolutionConfig.pool_size = 4`, `tournament_size = 2`.
  - `IslandState.cells: dict[str, str]` maps cell key to candidate ID.
  - `EvolutionState.assessments` and the `Assessment` record (promise rating 1 to 5, approach, novelty note, risk flags, model, prompt version).
  - `EvolutionLimits.max_critic_calls`.
- `evolution/engine.py`
  - `cell_key()` and `best_candidate_id()`.
  - Valid candidates fill their cell if they beat its incumbent. The pool is bounded: the weakest representative is evicted. The island elite is the best of the pool.
  - Tournaments sample `tournament_size` members of the pool using the seeded RNG. Mutation uses one tournament. Crossover takes a second tournament that excludes the first parent, falling back to the old distance rule.
  - New islands start with their founder in its cell.
- Invalid candidates never enter a pool.

### LLM critic

- `src/the_pigeon_holes/llm/critic.py`: `AnthropicCritic` with a forced tool call (`submit_assessment`). The system prompt says the candidate source is data. A malformed or failed reply returns `None`, and no assessment is recorded.
- `src/the_pigeon_holes/evolution/loop.py`: `_assess_valid()` runs after each committed batch and for the seed. It skips invalid candidates, reuses assessments by source fingerprint, and stops at `max_critic_calls`. Calls within a batch run concurrently.
- `src/the_pigeon_holes/evolution/prompting.py`: parent and inspiration sections include the assessment, labelled "advisory; measured evidence above is authoritative".
- `src/the_pigeon_holes/evolution/ports.py`: `CandidateCritic` protocol. The observer gains `assessment_recorded`.

### UI bridge

- `src/the_pigeon_holes/ui/contracts.py`: `assessment_recorded` added to the event types.
- `src/the_pigeon_holes/ui/bridge.py`: handles the event, keeps an `assessments` list in the snapshot, and emits the fields in camel case.

### Run script

- `scripts/run_autocorrelation.py`: wires evaluator, generator, critic, and loop. Writes `runs/<run-id>/attempts.jsonl` and `summary.json`. The summary re-runs the best candidate and recomputes C1 exactly, then reports whether it beats the published bound.
- Defaults: `--n 600`, `--max-tokens 200000`, `--max-minutes 30`, `--max-critic-calls 200`, `--memory-mb 256`. Model defaults to `claude-sonnet-5-5` (override with `LEVOLVE_MODEL` or `--model`).

## Deviations from the original plan

- **No contract shape change.** The fixed length `n` is a case parameter, so the existing contract and suite work as they are.
- **No Hypothesis.** It isn't installed, and adding it would change `pyproject.toml` and `uv.lock`, which already have unreconciled edits. Property checks are seeded randomised tests.
- **No critic prior on parent choice.** The critic only feeds prompts. Its bounded prior and its "disable if no better than chance" monitor are not built.
- **Critic budget** lives in `EvolutionLimits`, as planned.

## Tests

Run with `uv run pytest`. Current result: 104 passed, 1 failed. The failure is `test_proofnet`, which needs the `datasets` package that isn't installed in this environment.

| File | Covers |
| --- | --- |
| `tests/test_autocorrelation_judge.py` | Known answers (constant gives C1 = 2, a spike gives 2n), invalid inputs, scale and reversal invariance, a planted normalisation bug, and agreement with a float reference (copied from the Apache-2.0 upstream verifier logic) |
| `tests/test_autocorrelation_evaluator.py` | Real container runs: seed score, each failure stage, wrong length, stdout noise, descriptor cell. Skipped if Docker is unavailable |
| `tests/test_container_runner.py` | Sandbox flags are present and memory-swap equals memory |
| `tests/test_evolution_pools.py` | One representative per cell, bounded pool with weakest eviction, elite is the pool's best, invalid candidates excluded, seeded tournament reproducibility, full-pool tournament returns the best |
| `tests/test_critic_and_loop.py` | Critic sees only valid candidates, budget respected, critic output never changes validity or elites, missing assessments tolerated, prompt labels the note as advisory, parser rejects malformed output, critic refuses invalid candidates |

Dry run (not committed): a scripted generator proposed random step functions at `n = 64` through the real container evaluator. Result: 92 evaluations, 52 valid, best C1 ≈ 1.864, pools bounded at 4 cells.

## Known limitations

- **Metrics are floats.** `CandidateEvaluation.metrics` is `Mapping[str, float]`, so the engine ranks by float C1, and near-ties can be ordered wrongly. Claims are checked exactly only in the run script, on the final best candidate.
- **Lean is a placeholder.** The contract's Lean statement says it is pending review. Stage 1 confirmation isn't wired.
- **Units are easy to get wrong.** Plain integers such as `[1]*n` fail with "integral is too small". The prompt states the 2⁴⁰ convention, but a model may still miss it.
- **Duplicates are labelled `static_validation`.** This is existing loop behaviour. It inflates that stage's counts in logs, and a separate `duplicate` stage would be clearer.
- **Descriptor resolution is coarse.** At most 4 × 9 = 36 cells, so diversity is limited to that grid.
- **Container isolation is Docker's, not formally verified.** It is adequate for development, not a claim of security against hostile code.
- **Critic quality is unmeasured.** The planned per-island check of critic rank against stage 0 is not built.

## Running it

```
export ANTHROPIC_API_KEY=...
uv run python scripts/run_autocorrelation.py --seed 0
```

Requires the Docker daemon running and the worker image built (`docker build -t the-pigeon-holes/candidate-worker:v1 docker/worker`). No live run has been done yet; no API key was available.

## Next steps

1. Live run with a bounded budget, then inspect `attempts.jsonl` for invalid-output patterns and unit mistakes.
2. Decide whether to commit as one change or split by phase.
3. Add a `duplicate` failure stage in the loop.
4. Measure the critic's rank agreement with stage 0 over a run, and decide whether it earns a prior on parent choice.
5. Lean confirmation as a periodic audit (stage 1), after the loop is verified live.
