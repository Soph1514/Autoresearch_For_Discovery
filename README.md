# The Pigeon Holes

Algorithm autoresearch framework based on [the agreed design](context/agents.md).
The first implemented step is 0/1 knapsack specification validation.

Generate its formalisation with:

```python
from the_pigeon_holes import formalise

generated, instance = formalise("knapsack")
```

Set `LEA_ROOT` to the Lea checkout if it is not at `../lea-prover`. Set
`LEA_MODEL` to override Lea's default Gemini model. The function writes
`problems/knapsack/Generated.lean` and returns its path together with the original
natural-language instance. The next pipeline step receives those two values.

Benchmark references come from the pinned
[CAM-Bench](https://github.com/optpku/CAM-Bench) dataset:

```python
from the_pigeon_holes import pull_cam_bench

benchmark = pull_cam_bench("problem_directory_name")
general_problem = benchmark.informal_statement
reference_lean = benchmark.formal_statement
```

Problem directory names are mapped to CAM-Bench entries in
`problems/benchmark_map.json`. The dataset is cached under `runs/`; reference
Lean is not copied into problem directories.

```text
src/the_pigeon_holes/
    formalization/lea.py       Lea CLI integration
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

No reference for this knapsack instance exists in the projects listed by the
[Lean community project index](https://leanprover-community.github.io/lean_projects.html),
so the validator compiles `Generated.lean` and rejects
`sorry`, `admit`, and custom `axiom` declarations.

Run tests, including real Lean checks after setup:

```sh
LEAN_TEST_LAKE=lake PYTHONPATH=src:. uv run python -m unittest discover -v
```
