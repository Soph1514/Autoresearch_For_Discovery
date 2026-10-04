# GLM first-match cost versus Claude full-run cost

Benchmark date: 2026-10-04. Both arms had a $1 model API budget per
problem and identical initial system instructions, problem text, and submission
schema. Claude Opus 5.5 ran as a single agent; our pipeline used GLM-5.3 through
Modal. Subsequent search histories differed. Candidate programs were evaluated
in Modal sandboxes using the same frozen cases, scorer, and execution limits.

This table compares **GLM's estimated cost to first match Claude's final score**
with **Claude's full completed-run cost**. Claude continued until budget
admission stopped it. GLM costs are reconstructed retrospectively from the
existing run; this is not a fresh experiment with early stopping enabled.

| Problem | Claude Opus 5.5 | Our GLM-5.3 pipeline | Claude full cost | GLM first-match cost |
|---|---:|---:|---:|---:|
| Bin-packing ↓ | **63** | **63** | $0.6511 | **$0.1688** |
| Knapsack ↑ | **270** | **270** | $0.6274 | **$0.5776** |
| TSP ↓ | **144** | **144** | $0.6277 | **$0.1727** |
| Max-cut ↑ | **45** | **45** | $0.7129 | **$0.0699** |
| Makespan ↓ | **30** | **30** | $0.7147 | **$0.3226** |
| **Total** | | | $3.3338 | **$1.3116** |

**Bold** marks the best score and lowest cost in each row; tied scores are both
bold. ↓ means lower is better; ↑ means higher is better. Totals use unrounded
costs. GLM matches these five scores at approximately **61% lower cost under
this asymmetric stopping comparison**. This does not establish lower cost
under identical stopping rules or isolate the effect of orchestration.

## Cost reconstruction and limitations

- GLM first-match cost includes the eventual reported charges of every request
  whose saved prompt file modification time was no later than the earliest
  successful evaluation event matching Claude's final score. Requests already
  launched are counted even if they completed afterward. This reconstruction
  relies on the original local artifact timestamps; it is an estimate, not a
  provider-recorded cost-at-validation measurement.
- Failed submissions and costs from recovery segments remain included. Three
  GLM runs required recovery after all-malformed batches prematurely stopped
  search; their ledgers were preserved, without granting fresh budgets.
- Qwen interpretation and Modal sandbox compute are excluded. Preparation
  reused repository statements without new Qwen calls. GLM generation and
  critic charges are included; Claude costs include its entire completed run.
- Both arms used a 128,000-token generation ceiling, reduced to fit remaining
  budget, with a 16,384-token admission floor. There was no fixed 12k generation
  cap. Claude's unspent budget reflects inability to reserve its next request.
- Autocorrelation is excluded: GLM suffered an API error and a timeout, with
  unknown billing and no valid generated candidate. Its retained seed score of
  2.0 was not a match for Claude's 1.518532 mean replay score.
- This is one search run per arm/problem, with recovery segments where noted.
  Four problems reached all known optima; both arms scored 63 on bin-packing
  against a known aggregate optimum of 60. Fresh sandbox replay scores were
  independently recalculated. No fresh Lean proof check was performed.

## Artifact provenance

The local run identifier is `runs/dollar-glm-v2`, based on repository commit
`42fb5af` plus the benchmark harness and output-budget changes in the working
tree at execution time. Those uncommitted changes are not captured by the base
commit. This documentation commit does not package the harness or raw runs.

The source artifacts are each arm's `summary.json`, GLM `artifact.json` files
(including archived recovery segments), and the GLM `glm-api/budget.json` and
`call-*-prompt.json` files. The full-run audit is
`runs/dollar-glm-v2/comparison.json`; it reports full-run costs, not the
first-match estimates in this table.
