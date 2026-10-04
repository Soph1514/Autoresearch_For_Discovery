# Starting from a verified published construction

4 October 2026. The full-resolution refinement benchmark now starts from **AgentDiscover's public EinsteinArena solution 2603**, submitted 3 October 2026. It was the live leader when retrieved, at approximately **1.502743531954** using **65,536 cells**. This is an imported result, not our discovery. [Source leaderboard](https://einsteinarena.com/problems/first-autocorrelation-inequality).

The source witness, attribution and SHA-256 digest are pinned in `research/published-sidon/`. Normalizing its maximum height and rounding to the lab's 2^-40 convention gives the exact rational

```
1757730518180473131745912553472 / 1169680974034910581603041819889
```

This is approximately 1.5027435319538773. The difference from the posted floating-point score is rounding, not a claimed research improvement. Independent integer convolution, small-case checks against direct convolution, and a real Docker evaluation verify the imported baseline.

## Search result

[Open the saved run](http://127.0.0.1:5173/engine.html?run=bc5af04e-ff65-4ee6-a00a-fd872a1f94a2).

A six-minute Opus 5.5 high-reasoning run evaluated the seed and five generated refinements. **All six passed; none improved the baseline.** Three other generation attempts exhausted their output limit before submitting code. The winning seed is marked BEST in the DAG. All six saved witnesses were rescored during export. The run completed at its time limit; in-flight calls retain conservative cost reservations.

The final run cost an estimated **$1.70**, or **$2.74** including interrupted-call reservations. Across this entire published-seed follow-up, including the earlier experiments, recorded usage is **$4.97**, or **$8.19** conservatively. Combined with the previous budgeted work, this remains below the original $50 allowance. These are API usage estimates, excluding hosting and taxes.

## What changed

- Added a separate full-resolution refinement interface, `solve(initial: list[int]) -> list[int]`, and exact integer fitness. Candidates receive the public witness and must return a valid construction; they cannot simply report a score.
- Preserved the existing coarse autocorrelation benchmark. Projecting the older TTT-Discover 30,000-cell witness onto 32/64/128 cells loses its published bound, so these are explicitly different tasks.
- Found and fixed missing numeric execution limits in generation prompts. Earlier generated refinements chose 25–50 second internal budgets and failed the 15-second evaluator limit. The corrected run passed all submitted candidates under the unchanged limit.
- Reused the completed 28-source literature review in the corrected run and labeled that reuse in the UI. Both the imported baseline and its attribution are visible.
- Merged the teammates' newer benchmark and compiled-scorer work, retaining their registry, generic export and UI structure. No broad refactoring was performed.

The earlier TTT-seeded run was stopped to switch to the stronger live leader. The first live-leader run retained the seed but rejected timed-out refinements. Their original statuses and evidence remain available. Formalization is the previously reviewed mathematical statement; there is no new proof of optimality or claim that the refinement interface was automatically formalized.

Validation after integration: **307 backend tests passed, 29 skipped; 14 frontend tests passed; production build passed.** The saved run restored after restarting the backend, with baseline credit, reused review, final winner and the 65,536-value witness visible in the browser.

[Evidence bundle](../output/demo-verification/published-sidon-evidence.zip) contains run records, candidate code, exact witnesses, lineage events, pinned source data, provenance and verification logs. To prepare the seeded benchmark again, run `PYTHONPATH=src .venv/bin/python scripts/prepare_sidon_refinement.py`; it defaults to the pinned live leader. `--source ttt` selects the earlier paper baseline.
