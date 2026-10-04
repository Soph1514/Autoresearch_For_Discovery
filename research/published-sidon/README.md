# Published Sidon baseline

The pinned MIT-licensed TTT-Discover 30,000-cell construction reproduces **1.5028628982558014** after quantization to the lab's 2^-40 integer convention. Provenance, source digest and exact rational scores are recorded alongside the original JSON and license. This is reproduction of an existing result, not our discovery or a claim of optimality.

Projection to 32/64/128 cells gives 1.794568 / 1.665308 / 1.704803. Projection even to 4096 cells gives 1.625011. Therefore the full witness must be evaluated at its native resolution; its published score cannot be carried over to the old coarse benchmark.

The additive `sidon-refinement` fitness registry entry uses exact carry-free integer convolution and accepts `solve(initial: list[int]) -> list[int]`. Each candidate receives the public published witness, can perturb it or explore another construction, and returns the same number of nonnegative integer cells. Returning the initial witness is the baseline. Scoring uses the actual returned witness. The original autocorrelation evaluator remains unchanged.

Reproduce verification and register the contract:

```sh
PYTHONPATH=src .venv/bin/python scripts/verify_published_sidon.py
PYTHONPATH=src .venv/bin/python scripts/prepare_sidon_refinement.py
```

The second command runs the identity seed in Docker and stores a separate `sidon-published-30000-refinement-v1` contract in the local database. Restart an older backend after updating the registry. Start a custom run through `/api/runs` with that contract ID and an explicit dollar budget. This is a public construction-refinement benchmark; results are not comparable to the old three-resolution average. The existing Lean statement is retained as mathematical context, not a new proof of the refinement interface.
