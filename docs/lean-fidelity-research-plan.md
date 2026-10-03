# Lean fidelity classifier plan

Status: one training run, initialization comparison and external evaluation completed. Prompted Qwen baseline and workflow experiments remain planned. Updated 3 October 2026.

We will train a binary classifier to judge whether a candidate Lean statement faithfully expresses an English problem. It screens specifications before expensive algorithm search. It does not prove the theorem or establish that Python code implements it correctly.

The research question is: **does training reduce wrong specifications accepted into search, at comparable acceptance coverage and reasonable checking cost?**

## Model and input

Use **`Qwen/Qwen3-4B-Instruct-2507` + LoRA + a binary classification head**. Freeze the backbone and train the adapters and head. LoRA is a training method, not a second model.

```text
English problem + Lean context + candidate statement
    → Qwen with LoRA
    → final non-padding token representation
    → linear classification head
    → logit → calibrated probability → routing decision
```

Start with a 4,096-token budget. Include relevant definitions; exclude proof bodies, hidden reference formulations, labels, and comments revealing correctness. Route missing context or essential input overflow to review instead of silently truncating it.

The first experiment needs no Lean writer: ProofNetVerif already contains candidates. Later, use the downloaded `mlx-community/Qwen3.5-9B-MLX-4bit` through Lea to generate fresh candidates. Its server and tool compatibility still need testing.

Use **Modal GPUs for classifier training and GPU-based evaluation**, funded by the user’s confirmed **$150 in Modal credits**. The initial implementation targets one A100 80 GB; the account balance has not been independently checked. Run a memory and speed pilot on Modal before selecting the GPU and allocating the full training budget; log runtime, peak memory, and actual cost. The local M4 with 24 GB unified memory remains available for development and the downloaded MLX writer.

## Data and split

Use [ProofNetVerif](https://huggingface.co/datasets/PAug/ProofNetVerif):

| Field | Use |
| --- | --- |
| `nl_statement` | English input |
| `lean4_prediction` | Candidate Lean input |
| `lean4_src_header` | Lean context |
| `correct` | Label: 1 faithful, 0 misinterpreted |
| `lean4_formalization` | Hidden reference for audits only |

Pool the published splits and create a **custom grouped 80/20 split**, seed 42. Split by original problem ID, keeping duplicates and all derived variants together. This is not the official benchmark split; row proportions may differ from problem proportions.

Within the 80% allocation, reserve 10% of its problem groups for model selection and another 10% for calibration. Train on the remainder. Keep the final 20% untouched until settings and thresholds are locked. Report actual problem and row counts.

Audit labels and cross-dataset overlap. Exclude unresolved annotations from training. An unproved conjecture can still be faithfully stated: absent proofs or `sorry` placeholders do not automatically imply a negative label. Check statement elaboration separately.

Use CriticLeanBench for external evaluation. Curate additional labeled pairs from Formal Conjectures, Tao's Analysis I and Equational Theories projects, Lean Machine Learning, and our optimization tasks. These libraries are not ready-made binary datasets. Treat them as OOD tests only after checking overlap and domain differences.

Optional augmentation: add audited semantic mutations and alternative correct formulations. Wikipedia concept context must be retrieved from the English problem only, shared across that problem's candidates, and reproducible at deployment. Preserve the original statement and record source revisions. All augmentations inherit the original problem's split.

## Loss and training

For English problem x, candidate F, and context c, the classifier outputs logit s and probability p:

$$
p = \sigma(s_\theta(x,F,c)), \qquad y \in \{0,1\}.
$$

Use binary cross-entropy:

$$
\ell(y,s) = -y\log\sigma(s) - (1-y)\log(1-\sigma(s)).
$$

Implement it with `BCEWithLogitsLoss(reduction="none")` directly on logits for numerical stability. Average within each original problem, then across problems, so problems with many candidates do not dominate:

$$
\mathcal L_{\mathrm{train}}
= \frac{1}{M}\sum_{j=1}^{M}\frac{1}{n_j}
\sum_{i=1}^{n_j}\ell(y_{ji},s_{ji}).
$$

Here M is the number of training problems and n_j is the candidate count for problem j. Use a problem-balanced sampler (uniform problem, then uniform candidate) or correctly normalized weights to implement this objective in minibatches. Do not also reweight an already balanced sampler.

Start without class weighting. Handle the cost of accepting a wrong formulation through calibration and routing thresholds. Gradients update only LoRA adapters and the classification head.

Proposed pilot settings: LoRA rank 16, dropout 0.05, adapter learning rate 1e-4, head learning rate 1e-3, effective batch size 16, and development-loss early stopping (three evaluations without a 0.001 improvement, every 50 optimizer steps). One full Modal run is limited to one hour and a $20 budget; fixed resources are approximately $2.95/hour, with a conservative $5/hour allowance. Select the checkpoint using problem-balanced development loss. Save both adapters and head. Try BF16 LoRA first; use QLoRA if memory requires it and record the change.

After training, fit temperature T > 0 on the separate calibration subset using deployment-representative examples:

$$
p_{\mathrm{faithful}} = \sigma(s/T).
$$

Temperature scaling does not update the classifier. Choose routing thresholds on that same calibration allocation, then freeze them before test and external evaluation. Calibration is distribution-dependent, not a correctness guarantee.

## Output and routing

The model returns a logit. Calibration produces the probability; application code generates this JSON and assigns the decision. The first version produces no mathematical explanation.

```json
{
  "candidate_id": "example-candidate",
  "raw_logit": null,
  "p_faithful": null,
  "decision": "review",
  "reason_code": "not_scored",
  "model_revision": "to_be_pinned",
  "calibration_version": null,
  "specification_hash": "to_be_computed"
}
```

`raw_logit` is a finite real number; `p_faithful` is in [0, 1]. Either may be null when unavailable. The remaining non-enum fields are identifiers; calibration version is null before fitting.

| Condition | `decision` | `reason_code` |
| --- | --- | --- |
| Prerequisites pass and score meets acceptance threshold | `accept` | `high_alignment` |
| Score falls below rejection threshold | `revise` | `low_alignment` |
| Score lies between thresholds | `review` | `uncertain_alignment` |
| Statement fails elaboration | `revise` | `elaboration_failed` |
| Required definitions are missing | `review` | `missing_context` |
| Essential input exceeds context budget | `review` | `context_overflow` |
| Scoring fails | `review` | `scoring_failed` |
| Revision is needed but retries are exhausted | `review` | `retry_budget_exhausted` |
| Scoring has not run | `review` | `not_scored` |

Prerequisite failures block acceptance; use null scores for invalid or missing input. Scores belong to the exact statement/context hash and are invalidated after edits. Retry exhaustion overrides `revise`. A separate reviewer can diagnose rejected candidates, with its cost recorded.

A proposed calibration target is at most 5% incorrect specifications among accepted candidates. Report whether the evidence supports it and at what coverage. If no useful threshold qualifies, use the classifier for ranking or review only.

## Experiments

| Experiment | Method | Purpose |
| --- | --- | --- |
| A | Accept every elaborated statement | Operational baseline |
| B | Frozen Qwen4B prompted to judge the pair | Baseline without training |
| C | Qwen4B with LoRA and binary head | Primary comparison against B |
| D | C retrained with relevant Lean definitions | Context ablation |
| E | D retrained with Wikipedia concept context | Optional augmentation ablation |

Run B/C first with identical inputs. For B, normalize likelihoods of fixed faithful/misinterpreted label completions and document tokenization; do not use a generated percentage. Calibrate each scored method independently. Repeat training with three seeds if budget allows; otherwise report a single-seed experiment.

Later, pilot Qwen9B through Lea on 10 development problems, with proposed limits of 10 tool calls and 120 seconds per problem. Ask for statements and definitions rather than complete proofs. Keep references hidden, environments versioned, and candidate code separate from protected evaluator files.

Generate a frozen held-out candidate pool and compare gates on identical candidates. Then compare complete writer–gate workflows under equal total budgets, allowing at most two revisions after the initial attempt. Audit fidelity independently of the classifier. Record tool failures, elaboration, abstentions, runtime, and cost. If Lea integration fails, report that separately from offline classifier results.

## Figure and empty evaluation tables

The main plot is **incorrect acceptances versus acceptance coverage**. Lower error at equal coverage is better. Mark the calibration-selected operating point; test curves describe results and do not select new thresholds.

Coverage is accepted / eligible candidates. Accepted error is wrong accepted / all accepted; it is undefined when nothing is accepted. Report both the overall and elaborated-only populations. Faithful recall is faithful accepted / all faithful candidates. Brier score is the mean squared probability error on labeled scored examples.

Use paired bootstrap intervals grouped by original problem and show counts. Keep thresholds unchanged on external domains. Record revisions, split hash, seed, hardware, and run artifacts with every result. Dashes below mean unmeasured, not zero.

### Main comparison

| Gate | Coverage | Wrong accepted / accepted | Faithful recall | Brier score | Median / p95 latency | Cost per accepted faithful specification |
| --- | --- | --- | --- | --- | --- | --- |
| Elaboration only | — | — | — | N/A | — | — |
| Prompted Qwen | — | — | — | — | — | — |
| Trained classifier (single run) | 2.06% | 0 / 16 | 6.25% | 0.1370 | — | — |
| With Lean definitions | — | — | — | — | — | — |
| With Wikipedia | — | — | — | — | — | — |

### External and domain evaluation

| Evaluation set | Problems | Candidates | Coverage | Wrong accepted / accepted | Faithful recall | Brier score | Run artifact |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ProofNetVerif custom 20% test | 73 | 778 | 2.06% | 0 / 16 | 6.25% | 0.1370 | `run-20261003T192204Z` |
| CriticLeanBench | 447 | 450 | 0.44% | 0 / 2 | 0.80% | 0.2242 | `ood-comparison.json` |
| Formal Conjectures curated | 3 | 6 | 0.00% | 0 / 0 | 0.00% | 0.1925 | `ood-comparison.json` |
| Tao Analysis I curated | 4 | 8 | 25.00% | 0 / 2 | 50.00% | 0.0318 | `ood-comparison.json` |
| Tao Equational Theories curated | 4 | 8 | 0.00% | 0 / 0 | 0.00% | 0.0862 | `ood-comparison.json` |
| Lean Machine Learning curated | 4 | 8 | 0.00% | 0 / 0 | 0.00% | 0.0622 | `ood-comparison.json` |
| Team optimization tasks | — | — | — | — | — | — | — |

### Later writer workflow evaluation

| Workflow | Problems | First-pass elaboration | Final returned fidelity | Abstention rate | Total calls | Median / p95 time | Total cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Lea with elaboration gate | — | — | — | — | — | — | — |
| Lea with prompted fidelity gate | — | — | — | — | — | — | — |
| Lea with trained fidelity gate | — | — | — | — | — | — | — |

Final fidelity is measured among returned specifications; report abstentions separately. Claims of downstream compute savings require actual matched runs. If we instead assign a hypothetical cost to each accepted candidate, label savings as modeled estimates.

## Delivery order and later RL

1. Build audited data, grouped splits, and the prompted baseline.
2. Train and calibrate the classifier; lock thresholds.
3. Fill the main table and export the risk–coverage plot as PDF/PNG.
4. Add context ablations and external evaluations.
5. Test fresh Lea outputs and bounded repair workflows.

Later, freeze the classifier and use its probability as an RL reward proxy after validity checks. Verified reference mismatches override a high score. Retain independent fidelity audits to detect reward exploitation and distribution shift; increased proxy reward alone is not success.

## Sources

- [ProofNetVerif](https://huggingface.co/datasets/PAug/ProofNetVerif) and [evaluation paper](https://aclanthology.org/2025.emnlp-main.907/)
- [Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) and [Lea](https://github.com/VIDA-NYU/Lea)
- [CriticLeanBench](https://huggingface.co/datasets/m-a-p/CriticLeanBench)
- [Formal Conjectures](https://github.com/google-deepmind/formal-conjectures)
- [Tao Analysis I](https://github.com/teorth/analysis) and [Equational Theories](https://github.com/teorth/equational_theories)
- [Lean Machine Learning](https://leanmachinelearning.org/library/)

### First completed run — 3 October 2026

Qwen3-4B LoRA on one A100 80 GB in workspace `arin06` stopped after 400 steps (29.3 minutes of training) because three development evaluations failed to improve. Best checkpoint: step 250, problem-balanced development BCE 0.3823. The development curve is non-monotonic; this is an early-stopping result, not proven convergence. Calibration selected threshold 0.8275. Test coverage is low: only 16 acceptances out of 778, with zero observed accepted errors. This small accepted sample does not establish a zero error rate. The initialization and OOD comparisons are now reported below; prompted Qwen remains unmeasured. See `research/lean-fidelity/reports/full-run-result.json` and the executed notebook.

### Baseline and OOD results — 3 October 2026

Accuracy at probability threshold 0.5, on identical inputs for both models:

| Set | Candidates | Initial random-head classifier | Fine-tuned |
| --- | ---: | ---: | ---: |
| ProofNet train | 2,362 | 29.85% | 90.77% |
| ProofNet test | 778 | 32.90% | 80.85% |
| CriticLeanBench | 450 | 55.56% | 62.67% |
| Formal Conjectures probes | 6 | 50.00% | 50.00% |
| Tao Analysis I probes | 8 | 50.00% | 100.00% |
| Tao Equational Theories probes | 8 | 50.00% | 100.00% |
| Lean Machine Learning probes | 8 | 50.00% | 100.00% |

**Interpretation:** CriticLeanBench accuracy increased by 7.11 percentage points, but the paired problem-bootstrap 95% interval is −0.66 to +14.96 points (2,000 resamples, 447 groups). Balanced accuracy rose from 50.05% to 65.25%. At threshold 0.5 the trained classifier detected 177/200 incorrect formulations, but identified only 105/250 faithful formulations. The frozen ID gate accepted 2/450 with no observed errors; this is too little coverage to establish useful automatic acceptance. No thresholds were fitted on OOD labels.

The baseline is the **reconstructed original seed-42 random binary head**, not prompted Qwen. It scores 55.56% on CriticLeanBench, equal to the majority-class baseline. Thus these results do not demonstrate superiority over a competent pretrained LLM judge.

CriticLeanBench is the external labeled benchmark; 50 compilation failures without semantic labels were excluded. Its labels were used as published, without independent reannotation. Exact/near-text screening against every ProofNet split detected no overlaps, but does not rule out semantic overlap or pretraining contamination. The other four rows are **30 agent-authored, source-derived diagnostic probes**, with only 3–4 paired problems per library, no independent human audit or local Lean build, and mostly simple negation errors. Their 100% results cannot support broad domain generalization claims. Zero accepted rows means accepted error is undefined. No labeled team optimization set is available yet.

Pinned inputs, label rationales and adaptations: `research/lean-fidelity/ood_probes.json`. Metrics, source strata, predictions and PNG/PDF figures: `research/lean-fidelity/reports/ood-*`. The executed notebook contains both accuracy and risk–coverage plots. This single-seed experiment supports further OOD work; it does not establish a reliable RL reward model.
