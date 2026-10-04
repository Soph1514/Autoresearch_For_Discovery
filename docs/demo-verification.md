# Sidon-set demo verification — 4 October 2026

The demo runs the actual hosted preparation → extracted contract → Anthropic evolution
→ Docker execution → exact rational fitness → advisory critic → durable lineage path.
This is numerical witness search, not a proof of the optimal constant.

## Open locally

- Workbench: http://127.0.0.1:5173/
- Checked specification: http://127.0.0.1:5173/?formalization=68d3bc0f-2689-490d-a91c-40fefb47f490
- Initial live search: http://127.0.0.1:5173/engine.html?run=a628bc0e-3fd3-416b-92ec-eb5474add711
- Refinement: http://127.0.0.1:5173/engine.html?run=f79cdcaa-75bd-45b4-9868-558550f94ea9

Use `scripts/start_lab.sh` after stopping existing services. The launcher refuses
occupied ports rather than accidentally serving a different checkout. New paid
runs need the backend's Anthropic key, Modal authentication and Docker image.
Historical results require no new model calls.

## Preparation and scope

The pretrained Qwen model generated and attempted to repair the natural-language
problem. The checker rejected the attempts; they confused the mass constraint,
invented imports and used invalid Lean syntax. These attempts are preserved in
`runs/autocorrelation-preparation.ndjson`. They were stopped rather than accepted.

`problems/autocorrelation/Specification.lean` was then authored and reviewed with
assistance, submitted through the supported existing-Lean path, and checked with
Lean 4.19.0 and mathlib commit c44e0c8ee63ca166450922a373c7409c5d26b00b.
The source hash is d0b54bed13aca2d37049885823726583f20b7e3ec35949937035497eda72b641.
The fidelity classifier returned 0.5553 and **review**, not accept. The alignment
review was acknowledged before extracting the contract. This is not evidence of
fully autonomous natural-language formalization success.

The specification defines the continuous question with nonnegative extended
integrals and a supremum, plus the finite feasibility and rational c1 objective.
It does not prove the step-function reduction, Python correctness or optimality.
For equally spaced step functions the convolution is piecewise linear; its knot
values are the discrete convolution times the cell width. Consequently the exact
ratio is `2*n*max(convolve(q,q))/sum(q)^2`. The host fitness function uses integers/Fraction.

## Initial run

- Model: claude-sonnet-4-6, with forced structured tool output.
- Fixed evaluation sizes: 32, 64, 128. Mean c1 is minimized.
- Baseline: constant height, c1 = 2 exactly.
- Best: candidate-000014, mean c1 = 1.620383413986697 (18.98% below baseline).
- 18 candidate records; 15 valid, 3 rejected, 5 generation failures; 3 generations.
- 3 advisory critic reviews; 134 ordered saved events.
- 172,935 reported evolution tokens; 311.0 active seconds.
- Stop: no affordable request within the 180,000-token budget.
- All 48 recorded case witnesses independently recomputed from integer outputs.
  Some case evidence belongs to candidates that later failed another case.
- Unseen sizes 48/96/256 all passed, with scores 1.59551806 / 1.63092073 /
  1.92452590. The larger-grid degradation is a limitation, not hidden success.

The result is weaker than published upper-bound constructions. The supplied
problem table cites 1.5029; the AlphaEvolve paper reports 1.5032. Neither is a
baseline we beat. See [the original problem discussion](https://arxiv.org/html/2511.02864v3#S6.SS2).

Reported tokens exclude preparation. They are not a billed-dollar total; hosted
GPU/CPU charges and unknown in-flight billing are not measured here.

## Evidence and reproduction

The API download contains the immutable contract, provenance, prompts, source,
provider usage, failures, critic assessments, exact scores, integer outputs,
Docker image ID, event stream and final outcome. SQLite preserves this at
`runs/research.sqlite3`.

```sh
PYTHONPATH=src .venv/bin/python scripts/export_run.py a628bc0e-3fd3-416b-92ec-eb5474add711
PYTHONPATH=src .venv/bin/python scripts/verify_winner.py runs/exports/a628bc0e-3fd3-416b-92ec-eb5474add711/run.json
PYTHONPATH=src .venv/bin/python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

Exports include `run.json`, `events.ndjson`, `lineage.csv`, `best.py`,
`best-witnesses.json`, `summary.json` and `held-out.json`.

## Four-minute demo outline

1. **0:00–0:35:** Open the saved specification. Explain the open problem, checked
   definitions and the separate fidelity-review decision.
2. **0:35–1:15:** Open the initial run. Explain the constant seed, fixed test suite,
   token/time budgets and isolated execution.
3. **1:15–2:10:** Fit the lineage graph. Inspect an invalid candidate, a mutation,
   a two-parent merge, and the repaired winner. Show that failed ideas remain
   visible and measured failures cannot become elites.
4. **2:10–3:05:** Select the winner. Show witness plots and exact rational scores;
   expand its Python source and ancestry. Compare 2.0000 with the achieved score.
5. **3:05–3:40:** Open the refinement run and its saved history. Explain the
   advisory critic, pause/resume and persistence across restart.
6. **3:40–4:00:** Download evidence. State that this verifies the research system;
   it has not solved the open problem or beaten the published bounds.

No video or competition submission has been published.


## Final handoff

Three searches are preserved, including the failed refinement:

| Run | Candidates | Events | Best mean c1 | Reported tokens | Terminal status |
| --- | ---: | ---: | ---: | ---: | --- |
| Initial | 18 | 134 | 1.620383414 | 172,935 | completed |
| Refinement | 13 | 104 | 1.611190977 | 165,756 | failed (generation exhausted) |
| Compact-output verification | 10 | 66 | 1.611190977 | 70,802 | completed |

The final run is at http://127.0.0.1:5173/engine.html?run=bfcf0480-45f2-4c00-8643-23ad0692dc8e.
Its seed is the refinement winner. It generated nine further candidates without
truncated responses, but did not improve the seed. Do not present its inherited
score as a newly discovered improvement in that run.

Total: 41 candidate records, 304 events, 108 rechecked case witnesses and 409,493
reported evolution tokens. These are counts across runs, including repeated seeds
and witness outputs; they are not counts of distinct constructions.

The final best mean is 19.44% below the original constant seed. The refined winner
passed held-out sizes 48, 96 and 256, with mean 1.710538235. This is weaker than its
in-suite mean and illustrates the importance of held-out evaluation.

Final validation: 126 backend tests (real Docker checks included), six frontend
tests, production TypeScript/Vite build and git whitespace checks passed. UI
inspection covered mobile and desktop layouts, full lineage edges, inspection and
plots, saved history, formalization handoff, actual pause/resume, and reopening
completed runs. Docker cancellation and restart interruption are exercised by the
backend suite. A real backend restart reproduced the first run's snapshot exactly.
An export/import round trip into a separate store also succeeded.

`output/demo-verification/sidon-demo-evidence.zip` bundles all three run exports,
preparation attempts, specification, source, lineage CSV, verification logs and
this walkthrough. No credentials are included. Reproduction uses the pinned Docker
image ID and hosted Lean manifest captured in each run, rather than a claim of
bitwise reproducibility of external model generation.
