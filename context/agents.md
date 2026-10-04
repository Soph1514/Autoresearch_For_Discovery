# Project context

## Goal

Build a reusable algorithm autoresearch framework for Track 1, “Build Your Own Algorithm Autoresearch Framework.” The system should autonomously generate, implement, test, and improve algorithms for optimization and construction problems. Judging emphasizes novelty, performance, interpretability, and research efficiency.

## Agreed MVP foundation

Preserve the original pipeline. Focus the novel contribution on diversified, elite-preserving evolutionary idea generation rather than replacing the entire architecture.

1. **Natural-language specification:** define the problem, objective, and constraints.
2. **Lean formalization:** translate the specification into Lean and iterate with checker feedback. Checking a specification does not establish correctness of generated Python.
3. **Evolutionary idea generation:** select elite parents or explore new directions; mutate or combine ideas; check novelty and maintain diverse approaches.
4. **Python implementation:** implement and execute a candidate algorithm.
5. **Candidate object:** produce the constructed or optimized solution.
6. **Fitness and critique:** use a required trusted deterministic fitness function for validity and objective scores. An optional LLM critic may assess the idea and outcome, but cannot override executable validity checks or measured scores.
7. **Solution and elite archive:** retain verified winners across diverse niches and select them as parents for further experiments.
8. **Feedback and stopping:** return rejected attempts and experimental feedback to idea generation; return the best valid solution when time or cost limits are reached.

## Problem contract

The `ProblemContract` is the frozen hand-off from Lean formalization (step 2) to the evolutionary loop (steps 3–5). It binds the general Lean statement to an immutable evaluation suite and holds the complete versioned Python interface, a seed program, the optimisation goal (primary metric, aggregation, tie-breakers), per-evaluation resource limits, and a content-addressed reference to a required registered fitness function.

- The Lean statement and `solve` signature are general. The evaluator maps a candidate over the suite and aggregates metrics; generation prompts never contain case values.
- The contract builder preserves supporting types, validates the exact seed signature and every case value, and recursively freezes accepted suite data.
- The code-generation prompt includes the complete interface block from `render_solve_contract` in `src/the_pigeon_holes/llm/prompts.py`.
- Shared ownership, budget, pause/cancellation, and checked-Lean meanings are defined in [../docs/shared-semantics.md](../docs/shared-semantics.md).

Full definition, verification scope and known gaps: [../docs/problem_contract.md](../docs/problem_contract.md).

## Evolution principles

For the detailed and authoritative evolution-loop design, including executable
candidate generation, dynamic islands, elite and novelty archives, and stopping
rules, see [../docs/evolution.md](../docs/evolution.md). That document supersedes this file only
for evolution-specific behavior. In particular, evolutionary generation emits
the hypothesis and complete `solve(...)` implementation atomically; it is not a
separate idea-to-code translation stage.

- Ideas are hypotheses; elite status requires measured experimental evidence.
- Preserve strong candidates across behavioral niches rather than only one global winner.
- Diversity should reflect mechanisms or observed performance, not merely different wording.
- Candidate records should retain hypotheses, parent IDs, code versions, validity, scores, costs, and experimental evidence, including failures.
- Keep the specification, suite, optimization goal, and fitness function fixed during a run; periodic changes to the Lean specification are not an agreed requirement. The problem contract enforces this by being frozen.
- Aim to retain reusable algorithms, not just a good object for one evaluation case.

## Diagrams

- [MVP pipeline](autoresearch-pipeline.png): the accepted original pipeline with minimal additions for evolutionary ideation and elite preservation.
- [Idea lineage tree](idea-lineage-tree.png): the separate conceptual tree requested by the user. It shows a seed, mutations, tested/elite/failed descendants, an independent fresh idea, and a combination edge.

Keep the tree separate from the main pipeline diagram. The lineage is a graph internally because combinations may have multiple parents. These diagrams describe the proposed design, not an implemented or benchmark-validated system. Earlier expanded workflow and bin-packing example diagrams are superseded for this context package.

## Hackathon deliverables

Provide source code, installation and run instructions, high-level design, integrated benchmark examples, and a presentation video of at most four minutes. Demonstrate actual runs and reproducible evidence where possible. Submission details supplied by the user include a team name, repository URL, short description, and video link. Do not send the submission without explicit user authorization.
