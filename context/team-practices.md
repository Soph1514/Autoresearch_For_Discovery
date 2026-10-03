# Team practices

Applies to all four teammates and coding agents working on this hackathon repository.

## Hard rules

- **Never push directly to `main`.** Integrate changes through a reviewed pull request.
- **Push only to your own `feat/feature-name` branch.** Use a descriptive feature name; do not push to another teammate's branch.
- **Write only what is strictly necessary.** Do not bloat the code with speculative abstractions, unused helpers, extra dependencies, or unrelated refactors.
- **Protect the evaluator.** Generated candidates must not modify scoring, validity checks, or benchmark data. Agree on and version evaluator changes separately.
- **Protect teammates' work.** Never overwrite another teammate's uncommitted changes or force-push shared branches.

## Working guidelines

- Treat the agreed specification in `context/agents.md` and the approved pipeline diagram as the north star. Discuss changes to scope or architecture before implementing them.
- Keep code modular and coherent: small focused components, clear interfaces, descriptive names, and consistent conventions. Reuse existing code before adding new layers.
- Coordinate ownership across the four teammates. Agree on shared interfaces early and flag overlapping file changes before starting work.
- Keep each pull request focused and easy to review. Explain what changed, why, and how it was checked; get another teammate's review before merging.
- Use version control consistently: make small, focused commits with clear, concise messages describing the change. Avoid vague messages such as "updates" or "fix stuff".
- Regularly pull the latest changes from `main` into your feature branch, especially before starting work and opening a pull request. Commit or stash local changes first, and resolve conflicts promptly.
- Do not adopt TDD for now. Use focused checks where needed to verify behavior, especially candidate validity and benchmark evaluation.
- Add only files needed for the agreed feature. Avoid boilerplate, redundant documentation, generated clutter, and filler content. Keep temporary outputs and local artifacts out of commits.
- Before requesting review, inspect the diff, run the relevant checks, and remove accidental or unrelated changes. Never commit credentials or secrets.
