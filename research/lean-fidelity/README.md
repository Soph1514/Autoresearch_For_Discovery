# Lean fidelity

Qwen3-4B + LoRA judges whether Lean matches the problem. This is a classifier;
`modal_generation.py` uses pretrained Qwen to generate and repair Lean.
The backend checks Lean independently before scoring fidelity.

## Serving

Use Modal workspace `arin06`, environment `main`. From this directory, deploy
with `modal deploy --profile arin06 --env main <file>`:

- `modal_api.py`: frozen fidelity classifier.
- `modal_generation.py`: Lean generation, repair, and baseline judgments.
- `modal_checker.py`: Lean 4.19 / Mathlib checking.
- `modal_attachments.py`: image and PDF text extraction.

Run the backend with `MODAL_PROFILE=arin06`. Keep credentials on the backend.
GPU services scale to zero; requests can incur compute charges.
`frozen-model.json` pins the model, adapter hashes, storage and calibration;
`frozen_model.py` verifies and loads it. Do not overwrite the frozen weights.

## Training

Install this directory's Python 3.11 dependencies, then:

```sh
python experiment.py prepare
# Review artifacts/manifest.json and the prepared data before launching.
modal run --profile arin06 --env main modal_app.py --confirm-training
```

One A100 runs training, calibration and final evaluation under a one-hour limit.
Problem-grouped splits keep exact normalized-English duplicates together.
LoRA rank 16; problem-weighted binary cross-entropy; development early stopping.
The selected checkpoint was step 250. The calibrated gate accepted 16/778 held-out
candidates with zero observed errors (2.06% coverage); this is not a guarantee.
Weights and full run artifacts remain in the Modal volume, outside Git.

## Ten-problem comparison

```sh
MODAL_PROFILE=arin06 python benchmark_lea_ten.py
```

[Results and timings](reports/lea-ten-fidelity-comparison.html) and
[recorded predictions](reports/lea-ten-fidelity-comparison.json): initial Qwen
**7/10**, fine-tuned classifier **9/10**, judging identical dataset candidates.
Selection follows the merged Lea runner's first ten unique validation IDs; the
friend's actual run is unconfirmed. Eight problems overlap training, one development,
and only one is held out, so this is not a clean generalization benchmark.
Timings are single warm requests including RPC overhead. Lea timings are unavailable.

Exploratory notebooks, plots and OOD scripts were removed from this merge;
their original versions remain in Git history at `b8bd87b`.
