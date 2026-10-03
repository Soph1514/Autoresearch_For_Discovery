# The Pigeon Holes

Algorithm autoresearch framework based on [the agreed design](context/agents.md).
The first implemented step is 0/1 knapsack specification validation.

Generate its formalisation with:

```python
from the_pigeon_holes import formalise

generated, instance = formalise("knapsack")
```

The first run downloads the pinned Lea checkout under `runs/lea-prover`. Set
`LEA_ROOT` to use an existing checkout instead. Set `LEA_MODEL` to override
Lea's default Gemini model. The function writes
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

Then run BEq+ locally as often as needed without making API calls:

```sh
uv run python -m the_pigeon_holes.formalization.benchmark
```

The default Lea model uses `ANTHROPIC_API_KEY` from the repository's ignored
`.env` file. Use `LEA_MODEL` to select another Lea-supported provider.

```text
src/the_pigeon_holes/
    formalization/lea.py       Lea CLI integration
    formalization/beq_plus.py  Bidirectional semantic-equivalence checker
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
