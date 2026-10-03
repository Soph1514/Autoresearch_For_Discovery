# The Pigeon Holes

An algorithm autoresearch framework scaffold based on [the project context](context/agents.md) and its [MVP pipeline](context/autoresearch-pipeline.png). The pipeline and benchmarks are not implemented yet.

## Directory structure

```text
context/                       Original requirements and diagrams
src/the_pigeon_holes/
    pipeline/                  Research loop, feedback, time and cost limits
    models/                    Shared problem, idea, candidate and result records
    specification/             Natural-language problem, objective and constraints
    formalization/             Lean translation and checker feedback integration
    evolution/                 Parent selection, fresh ideas, mutation, combination,
                               novelty checks and behavioral diversity
    execution/                 Python generation and isolated candidate execution
    judging/                   Deterministic validity/scoring and LLM assessment
    archive/                   Verified elites by niche, evidence and lineage graph
    llm/                       Model client adapters and prompt handling
lean/
    ThePigeonHoles/             Lean definitions and specification support
problems/                      Benchmark problem packages
configs/                       Run settings, model choices and budget settings
tests/
    unit/                      Component tests
    integration/               Pipeline and tool integration tests
docs/                          Design, reproducibility and presentation materials
runs/                          Generated run artifacts (ignored by Git)
pyproject.toml                 Existing Python project metadata and dependencies
uv.lock                        Dependency lockfile
```

Each future `problems/<name>/` package should keep its natural-language specification, Lean specification, fixed deterministic evaluator, instances and baseline algorithms together. This keeps the framework reusable across optimization and construction problems.

Each future `runs/<run_id>/` directory should retain configuration, random seeds, fixed specification/evaluator snapshots, generated code versions, constructed objects, validity results, scores, costs and experimental evidence, including failed attempts.

## Component boundaries

The `pipeline` coordinates specification → formalization → evolution → execution → judging → archive, feeding experimental results and preserved elites back into evolution. It stops at the time or cost limit and returns the best valid solution.

The `models` records should distinguish an algorithm idea, its generated implementation and its output object. They should retain hypotheses, parent IDs, code versions and measured evidence. The `archive` maintains lineage as a graph because combination can have multiple parents; the [separate lineage diagram](context/idea-lineage-tree.png) is a tree-style view of that graph.

Lean checking validates the formal specification, not generated Python correctness. Deterministic executable validity checks gate acceptance; LLM assessments cannot override failure. Elite status requires measured evidence, with winners preserved across behavioral niches. Specifications and evaluators stay fixed during a run.

## Development setup

Install the existing dependencies with `uv sync`. Source packages live under `src/`; no CLI, build configuration, Lean toolchain or runnable research loop has been added yet. Add installation and run instructions as those components are implemented.
