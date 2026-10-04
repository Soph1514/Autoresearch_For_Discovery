# The Pigeon Holes

Algorithm autoresearch framework based on [the agreed design](context/agents.md).
The AntiAI UI supports hosted Lean generation, checking/repair and fidelity review,
plus custom evolution through the built-in autocorrelation Docker evaluator and
a separate routing demo. Start with the [UI setup](frontend/README.md);
see [integration status](docs/ui-integration-status.md) for remaining gaps.

The Lea CLI path below supports 0/1 knapsack specification validation.

Generate its formalisation with:

```python
from the_pigeon_holes import formalise

generated, instance = formalise("knapsack")
```

The first run downloads the pinned Lea checkout under `runs/lea-prover`. Set
`LEA_ROOT` to use an existing checkout instead. Set `LEA_MODEL` to override
the configured default Anthropic model. The function writes
`problems/knapsack/Generated.lean` and returns its path together with the original
natural-language instance. The next pipeline step receives those two values.

The formalizer benchmark uses natural-language statements and trusted Lean 4
references from [ProofNetVerif](https://huggingface.co/datasets/PAug/ProofNetVerif).
Generate predictions with Lea once (the default is ten unique validation items):

```sh
uv run python -m the_pigeon_holes.formalization.generate_benchmark
```

Generation saves each result immediately and resumes without repeating API calls.
Use `--limit 0` to generate every unique item:

```sh
uv run python -m the_pigeon_holes.formalization.generate_benchmark --limit 0
```

Generate the semantic-equivalence proofs separately:

```sh
uv run python -m the_pigeon_holes.formalization.generate_validation
```

Then check the saved Lean proofs locally as often as needed without making API calls:

```sh
uv run python -m the_pigeon_holes.formalization.benchmark
```

Run all three stages and record per-problem time, tokens, cost, and results in
`problems/proofnetverif/results.csv`:

```sh
uv run python -m the_pigeon_holes.formalization.run_benchmark_pipeline
```

Add `--force` to regenerate existing paid artifacts and collect fresh end-to-end
generation metrics.

The default Lea model uses `ANTHROPIC_API_KEY` from the repository's ignored
`.env` file. Use `LEA_MODEL` to select another Lea-supported provider.

Each generated benchmark directory contains only the specification and its
three Lean artifacts:

```text
problems/proofnetverif/valid/<problem>/
    Spec.txt
    Generated.lean
    Reference.lean
    Verification.lean
```

```text
src/the_pigeon_holes/
    formalization/lea.py       Lea CLI integration
    formalization/benchmark.py Checks Lean semantic-equivalence proofs
    formalization/validate.py  Compilation and cheating check
    specification/            Problem loading
    models/                   Shared records
    evolution/                Idea generation and selection
    execution/                Candidate implementation and execution
    judging/                  Validity and objective scoring
    archive/                  Elites, evidence and lineage
    pipeline/                 Research loop and budgets
    llm/                      Shared model integration
problems/
    lea_task.txt              Shared Lea formalization contract
    lean/                     Shared pinned Lean and mathlib project
problems/knapsack/
    problem.txt               General natural-language problem
    instance.txt              Concrete instance to solve
    Generated.lean            Lea-generated general specification
    test_validation.py        Runs this problem's Lean validation
context/                      Requirements and diagrams
configs/                      Run settings
runs/                         Generated evidence (ignored by Git)
tests/                        Validator and integration checks
```

## Setup and run

Install Python dependencies with `uv sync`, and install [elan](https://github.com/leanprover/elan)
for Lean. Prepare the problem's Lean project:

```sh
cd problems/lean
lake update
lake exe cache get Mathlib.Algebra.BigOperators.Group.Finset.Basic
lake build
cd ../..
```

If macOS rejects the cache executable, use
`lake env lean --run .lake/packages/mathlib/Cache/Main.lean get Mathlib.Algebra.BigOperators.Group.Finset.Basic`
from the same Lean directory.

Validate the generated specification:

```sh
uv run python -m the_pigeon_holes.formalization.validate \
  problems/knapsack
```

For NL formalization, use [Lea's prover](https://vida-nyu.github.io/Lea/).
Clone the linked prover repository outside this project and install its dependencies:

```sh
git clone https://github.com/darturi/lea-prover.git ../lea-prover
git -C ../lea-prover checkout 2709009dca410c1fc4d8de55f4e272f715b18334
uv sync --project ../lea-prover
```

The application validator compiles `Generated.lean` and rejects `sorry`, `admit`,
and custom `axiom` declarations when no reference exists. ProofNetVerif is a
separate statement-formalization benchmark and permits an omitted theorem proof.

Run tests, including real Lean checks after setup:

```sh
LEAN_TEST_LAKE=lake PYTHONPATH=src:. uv run python -m unittest discover -v
```


## Autocorrelation evaluator

The merged evaluator executes candidates in Docker and scores their integer
outputs with an exact rational judge. It supports `solve(n: int) -> list[int]`,
mean `c1` minimization and evaluator version `autocorrelation-exact-v1`.

```sh
docker build -t the-pigeon-holes/candidate-worker:v1 docker/worker
PYTHONPATH=src .venv/bin/python scripts/run_autocorrelation.py \
  --model "$RESEARCH_MODEL" --n 64 --max-tokens 32768 --max-minutes 5 \
  --max-critic-calls 0
```

Set `ANTHROPIC_API_KEY` and select a model first. This CLI is a numerical benchmark:
its Lean contract is a placeholder. The custom UI requires real checked Lean with
provenance. See [current evaluator status](docs/candidate-evaluator-plan.md) and
[the reconciled TODO list](docs/pipeline-next-steps.md).

## Sidon-set end-to-end demo

Run `scripts/start_lab.sh` to start this checkout on localhost:5173 with its API on
8000. It refuses occupied ports to avoid accidentally displaying another checkout.
The compatible default research model is `claude-sonnet-4-6`; set the Anthropic key
in the launching environment. Docker and the deployed Modal services are required
for new custom runs. Saved runs remain viewable without fresh model calls.

`problems/autocorrelation/problem.txt` and `Specification.lean` define the open
problem and finite witness-search contract. The reviewed specification was checked
with the hosted pinned Lean 4.19 checker. It does not prove the analytic reduction,
Python correctness, or the optimal constant. Natural-language Qwen generation is
also available, but can need manual correction; compiler acceptance alone does not
establish fidelity.

The engine supports direct `/engine.html?run=RUN_ID` links, saved history, live
lineage, best-candidate inspection, witness plots and exact rational certificates.
The custom form can enable bounded advisory critic calls sharing the generation
token budget. Export all events, lineage, best source and independently recheck
saved integer witnesses with:

```sh
PYTHONPATH=src .venv/bin/python scripts/export_run.py RUN_ID
```

See [the demo verification report](docs/demo-verification.md) for run links,
measured results, limitations and a four-minute presentation outline. Exported
runs can be imported into a fresh local store without executing their source:

```sh
PYTHONPATH=src .venv/bin/python scripts/import_run.py path/to/run.json
```
