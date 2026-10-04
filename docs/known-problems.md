# Built-in construction optimization problems

These are hand-written, deterministic fitness functions. They score a candidate's
constructed object; a feasible but suboptimal object remains valid. Automatic
fitness-function generation is not implemented.

All six families are in the trusted fitness registry and the generic CLI runner.
The four additions use integer objectives with `exact-v1` implementations.

| CLI problem | Constructed object | Objective | Baseline |
| --- | --- | --- | --- |
| `autocorrelation` | Nonnegative step-function heights | Minimize exact rational `c1` | Constant function |
| `bin-packing` | One bin label per item | Minimize occupied `bins_used` | First-fit decreasing |
| `knapsack` | Distinct selected item indices | Maximize `total_value` within capacity | Value/weight greedy |
| `tsp` | Permutation of all cities | Minimize closed `tour_length` | Nearest neighbor |
| `max-cut` | Binary vertex partition | Maximize crossing `cut_weight` | Greedy vertex insertion |
| `makespan` | One machine label per job | Minimize maximum machine load (`makespan`) | Longest-processing-time first |

## Objective sources and supported variants

Definitions checked on 4 October 2026. These sources establish the objective and
constraints; our implementations are written locally, without importing solver
code or runtime dependencies.

- **Bin packing:** minimize the number of used bins, assign each item once, and
  keep each bin within capacity. [Google OR-Tools definition and model](https://developers.google.com/optimization/pack/bin_packing).
  The existing triplet fixtures have a constructive optimum and a matching
  volume lower bound.
- **0/1 knapsack:** maximize selected value subject to total weight at most the
  capacity. [Google OR-Tools](https://developers.google.com/optimization/pack/knapsack).
  Our variant allows nonnegative integer weights, values and capacity, including
  zero-weight items and the empty selection. Selecting an item twice is invalid.
- **Symmetric TSP:** minimize total tour cost while visiting every city once and
  returning to the start. [Google OR-Tools](https://developers.google.com/optimization/routing/tsp).
  Our input is a complete, symmetric, nonnegative integer cost matrix with zero
  diagonal. Triangle inequality is not required. Output omits the repeated start;
  the scorer includes the closing edge, including both legs of a two-city tour.
- **Weighted max cut:** maximize the sum of nonnegative edge weights crossing a
  partition. [Keetch and van Gennip, *A Max-Cut approximation using a graph based MBO scheme*](https://arxiv.org/abs/1711.02419).
  Our variant uses integer weights and a simple undirected edge list. Duplicate
  edges, self-loops and out-of-range endpoints are rejected. Empty edge sets and
  empty partition sides are allowed; each edge is counted once.
- **Identical-machine makespan:** minimize maximum job completion time.
  [Albers and Hellwig, *Online Makespan Minimization with Parallel Schedules*](https://arxiv.org/abs/1304.5625)
  defines the identical-machine objective. Our solver receives all jobs at once
  (offline), with positive integer durations, release time zero, no preemption,
  no precedences and no setup times. A machine executes its assigned jobs back to
  back, so makespan is its maximum load. No online competitive guarantee is claimed.

Autocorrelation retains its existing exact scorer and
[documented numerical/Lean scope](candidate-evaluator-plan.md).

## Instances and qualification

Each new family has three fixed instances in `problems/<name>/instances.json`,
alongside its `problem.txt` and `fitness.py`. Folder names use underscores
(`bin_packing`, `max_cut`); CLI problem names retain their hyphens.
The knapsack suite includes the existing five-item
instance from `problems/knapsack/instance.txt`.

These twelve fixtures are local examples of established problems, not downloaded
benchmark datasets. Each file contains inputs, an optimum target, its justification,
and an attaining witness. Tests independently enumerate all possible constructions
and recompute the optimum. Targets and stored witnesses are used for tests and
post-run reporting only: they do not enter the contract, fitness logic or model
prompts. The scorer computes the objective directly from the submitted output.

The baseline is valid on every instance, and each new family has at least one
instance where its baseline is strictly suboptimal. These small examples qualify
scoring and exercise the loop; they are not evidence of research-scale performance.

The new scorers reject malformed outputs (including bools masquerading as ints),
infeasible constructions, and incompatible contracts. Tests cover independent
objective calculations, exhaustive optimum checks, zero/boundary cases, and
representation invariances: subset order, tour rotation/reversal, swapping cut
sides and permuting machine labels. Generic evaluator tests check aggregation and
stored evidence; optional Docker tests run all four baselines.

Input limits bound host work: 4,096 items/jobs/vertices; 256 TSP cities/machines;
65,536 max-cut edges; numeric inputs at most 1,000,000,000. Knapsack lists must
be nonempty. Each new suite uses the sum of its case objectives, with no tie-breaker.
Behavioral descriptors are bounded diversity features, not extra fitness terms.
Scores are integers in the fitness functions; the existing evolution interface
converts aggregate metrics to floats.

The shared fitness protocol and registry remain in
`src/the_pigeon_holes/fitness/`. Problem-specific scoring lives exclusively in
`problems/<name>/fitness.py`; imports use, for example,
`from problems.knapsack.fitness import KnapsackFitnessFunction`.

## Running

```sh
docker build -t the-pigeon-holes/candidate-worker:v1 docker/worker
uv run python scripts/run_problem.py --problem knapsack \
  --model "$RESEARCH_MODEL" --max-minutes 5 --max-critic-calls 0
```

Set `ANTHROPIC_API_KEY` for the live search. Substitute `tsp`, `max-cut`,
`makespan`, `bin-packing` or `autocorrelation`. The runner records every
attempt, re-executes the winner and compares its scores with the stored targets.
The new CLI contracts explicitly mark Lean as pending; numerical fitness checks
do not certify a Lean proof. The custom UI still requires a checked formalization.

```sh
uv run python -m pytest -q tests/test_construction_fitness.py
```

No model calls are made by these tests. Docker tests skip when preflight fails.
