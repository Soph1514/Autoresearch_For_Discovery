# Connected research trees

Open `/engine.html?view=forest` for the combined view. Add a problem (text or a photo),
review the specification and evaluation inputs, enter a mathematician's name, and
start research. Each run has its own shareable `/engine.html?run=<id>` page and 2D
lineage. The combined view projects those trees into rotatable 3D planes. Select a
node to open its page; select a connection to inspect both endpoints and evidence.
No new runtime dependencies are required.

## Coordination

`ui/forest.py` is the coordinator and shared archive. Each tree retains its own
immutable problem contract, budget, evolution islands, generator and evaluator.
Two generation/evaluation **batches** can execute across trees concurrently; each
provider retains its existing per-batch concurrency limit. Provider calls for
literature and optional critics retain their existing run budgets and limits.
Budgets are per tree, not a single shared dollar cap.

The scout runs after a new tree's seed is recorded, every 10 completed generations
within a tree, and a valid best score improves by more than 1% relative to the last
material improvement (absolute epsilon 1e-12). A generation is one committed batch,
not one model call or candidate. Smaller improvements accumulate. A new tree or
material improvement also prompts discovery for other active trees. Overlapping
triggers at a boundary are coalesced.

For a light first implementation, retrieval ranks evaluated elites by shared words
in the problem, hypothesis and mechanism tags. It does not make a provider call or
assert mathematical compatibility. At most one transfer per receiving tree is
pending. One request in its next generation becomes a transfer-specialist task;
other requests keep the existing mutation/crossover/restart policy. The task receives
a bounded source summary, interface, code and source metrics, with the destination
contract unchanged. Benchmark case inputs are never included by the coordinator.

This is task-based agent coordination: the existing generator handles explorer and
transfer-specialist roles, the deterministic scout selects evidence, and the trusted
evaluator judges the result. There are no always-on extra model agents.

Every bridge stores globally scoped source and target IDs, trigger reasons, source
evidence, dispatch baseline, adaptation hypothesis and destination evaluation. States
are proposed, testing, evaluated, improved, rejected, failed, or interrupted. An
improvement means the transfer-task candidate beat the destination best at dispatch;
it does not prove that the imported method caused the gain. Relations currently
represent technique-transfer attempts, not proved reductions or equivalences.

Both tree pages expose the trace; candidate inspectors show their own connections.
`GET /api/forest` is a compact view (polled every two seconds); full source evidence
is lazy-loaded through `GET /api/forest/bridges/<id>`. Existing per-run SSE stays intact.
SQLite stores the archive and traces. On restart, interrupted runs and outstanding
transfers are retained, marked interrupted/stopped, and never silently restarted.

## Verification

- `pytest tests/test_research_forest.py tests/test_ui_bridge.py` exercises concurrent
  runs, trigger timing/deduplication, prompt transfer, destination evaluation,
  durable evidence, recovery, and shared concurrency/cancellation.
- `npm test --prefix frontend` checks scoped IDs, projection, navigation URLs and
  the existing replay/lineage contracts.
- `npm run build --prefix frontend` checks types and produces both UI entry points.
- Start two offline routing demos through `POST /api/runs` with different `author`
  values to inspect navigation and the complete trace lifecycle without model calls.
  Demo traces are labeled and never used as evidence in real research trees.

Photo transcription, formalization, live model reasoning and candidate execution
still use the existing configured services. Offline tests establish coordination,
not the quality of mathematical transfer. Different formulations with no shared
vocabulary may be missed by the lightweight scout. Formal reduction verification
is not automated by this feature.
