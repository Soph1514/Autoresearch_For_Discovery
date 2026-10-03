# Lean fidelity research

Independent Qwen/Qwen3-4B-Instruct-2507 + LoRA binary classifier. The [research plan](../../docs/lean-fidelity-research-plan.md) describes the experiment; `research.ipynb` is the human-readable view. Run All analyzes local reports and never launches cloud training.

## Run

From this folder, after preparing and reviewing `artifacts/manifest.json`:

```sh
uv run --python 3.11 --with 'modal>=1.0,<2' python -m modal run --profile arin06 --env main modal_app.py --confirm-training
```

One Modal A100 80 GB performs training, calibration, then one final test. Each invocation gets a unique volume directory. The launcher downloads reports and plots; adapters remain in the `lean-fidelity-research` volume. CPU data preparation, if needed:

```sh
uv run --python 3.11 --with datasets==4.1.1 --with transformers==4.56.2 python experiment.py prepare
```

## Stopping and cost

Stop training when development BCE fails to improve by 0.001 for three consecutive evaluations, performed every 50 optimizer steps. This is an operational plateau criterion, not proof of convergence. Save the checkpoint with lowest development loss. Use a constant learning rate so a long nominal epoch limit does not define the schedule.

The single run has a one-hour absolute deadline from submission, including loading and evaluation. Training stops five minutes before it to reserve time for saving, calibration and final test. Each subprocess has a timeout; the caller cancels and terminates containers at the deadline. The remote function also has a one-hour timeout. No configured retries, one container, two-second idle shutdown. A restarted input refuses to overwrite the run directory.

Resources: A100 80 GB, up to four CPU cores, hard 32 GiB host RAM limit. Published rates on 2026-10-03 imply approximately $2.95/hour. The budget calculation uses a conservative $5/hour plus $1 overhead allowance against the authorized $20. The hour limit therefore binds first. This bounds this experiment's resource use; it is not an account-wide live billing cutoff, and does not cover unrelated jobs or indefinite storage retention. Starter does not offer environment budgets. See [Modal pricing](https://modal.com/pricing).

## Data and loss

Pinned ProofNetVerif: 2,362 training rows (232 problem groups), 309 development rows (28), 303 calibration rows (28), and 778 test rows (73). A grouped 80/20 split reserves development and calibration inside the 80%. Exact normalized-English duplicates stay together. No rows excluded; maximum input length 369 tokens. Near-duplicate and annotation audits remain manual.

Binary cross-entropy on one logit, weighted per example by N/(M*n_j) to give each problem equal expected training weight. LoRA rank 16, dropout 0.05, adapter learning rate 1e-4, head 1e-3, BF16, batch 2 × accumulation 8. Adapters and head are saved together. Development and test data never supply gradient updates.

Calibration fits temperature and chooses an empirical <=5% accepted-error threshold with >=20 accepts. No qualifying threshold disables automatic acceptance. Calibration settings are separate from the immutable calibration dataset. Final test is evaluated once after checkpoint/threshold selection; its metrics cannot be overwritten. A time cutoff can leave evaluation incomplete. Reports distinguish a completed evaluation from an interrupted run.

## Notebook

```sh
uv run --no-project --python 3.11 --with jupyterlab --with ipykernel --with pandas --with matplotlib jupyter lab research.ipynb
```

The notebook displays the real training function, available loss curves, stop reason and final metrics. Missing results are shown explicitly. The notebook also displays initialization-versus-fine-tuning comparisons and external evaluations. The initialization baseline has a random binary head; a prompted Qwen baseline remains unmeasured.

## Modal access

The training workspace is now `arin06`, environment `main`; A100 80 GB allocation was verified successfully. Runs use that workspace’s billing and credits. The original workspace is `mashathepotato`. The open dashboard showed $151 credit and $0 current spend on 2026-10-03, alongside a payment-method notice. The A100 API rejected allocation without a payment method. Credits and GPU access are separate in this workspace. Adding payment information must be done by the account owner, or organizers/Modal can resolve the access restriction. No credentials belong in this repository.

## One-hour laptop experiment

`local_run.py` downloads **Qwen/Qwen3-0.6B**, pins its revision, and reuses the original training/development groups. It trains FP32 LoRA plus the binary head on Apple Metal; batch 2, accumulation 8, the same learning rates/loss. Development evaluation occurs every 20 optimizer steps. Full train/dev data are used; calibration and test are not loaded. This is a smaller-model feasibility result, not a 4B benchmark.

```sh
uv run --no-project --python 3.11 --with torch==2.7.1 --with transformers==4.56.2 --with peft==0.17.1 --with datasets==4.1.1 --with accelerate==1.10.1 --with matplotlib==3.10.6 python local_run.py
```

The one-hour subprocess timeout starts after download and includes model loading. A graceful stop at 55 minutes reserves five minutes for evaluation/checkpoint saving. A hard cutoff preserves previously saved checkpoints and logs, but can interrupt the latest save. The notebook currently selects the latest Modal `artifacts/run-*` run; change its run selector to `local-*` to inspect the interrupted laptop experiment. It plots actual minibatch and full development BCE. Lower training loss alone does not establish generalization or convergence.

## Completed Modal run

`run-20261003T192204Z` completed on `arin06` with one A100 80 GB. Training stopped at 400 steps after three non-improving development evaluations (29.3 minutes training; roughly 33 minutes total app time). The final adapter matches checkpoint 250 byte-for-byte; best development BCE was 0.3823. Estimated compute was about $1.6 at the maximum configured resource rates, not a retrieved invoice total. The app is stopped.

The calibrated gate accepted 16/778 held-out candidates with 0 observed errors, 2.06% coverage and 6.25% faithful recall. Brier score: 0.1370. This is low coverage, and zero errors among 16 acceptances is not a guaranteed zero error rate. The later OOD audit reports 62.67% accuracy on CriticLeanBench, with limited acceptance coverage; prompted-baseline superiority remains untested. Full metrics and provenance are in `reports/full-run-result.json`; weights, raw predictions, and plots are in `artifacts/run-20261003T192204Z/`. The executed notebook embeds the loss curves and results. The earlier laptop experiment was stopped at the user's request after four optimizer steps.

## External evaluation

`prepare_ood.py` pins CriticLeanBench and combines its 450 semantically labeled examples with 30 source-derived contrast probes in `ood_probes.json`. It excludes 50 compilation failures, strips placeholder proofs/comments, checks exact and five-token-shingle overlap against every ProofNet split, and refuses input truncation. No overlaps were detected by this screen; semantic overlap and backbone pretraining contamination are still possible. Source revisions, input hash and exclusions are recorded in `artifacts/ood-v1/manifest.json`.

The four library sets are **small agent-authored diagnostics**, with 3–4 paired problems each. They are not benchmark labels supplied by the library authors, and have not had independent human review or local Lean elaboration. Most negative examples simply negate a statement; they do not represent realistic writer errors. Formal Conjectures supplies proposition definitions, including open conjectures: the label is fidelity, not truth. Probe JSON records English, context, candidates, source links, adaptations and label rationales. Team optimization tasks remain unmeasured because no labeled set has been supplied.

Reproduce preparation once (output must not already exist), then evaluation and local reporting:

```sh
uv run --no-project --python 3.11 --with transformers==4.56.2 --with datasets==4.1.1 python prepare_ood.py
uv run --no-project --python 3.11 --with 'modal>=1.0,<2' python -m modal run --profile arin06 --env main ood_eval.py
uv run --no-project --python 3.11 --with matplotlib==3.10.6 python summarize_ood.py
```

The evaluation is capped at 15 minutes on one A100 80 GB, with no retries or optimizer updates. It verifies the saved adapter hash and scores the same frozen rows for both models. Both accuracy columns use threshold 0.5. Fine-tuned gate metrics reuse the original ID temperature and acceptance threshold; the random-head baseline uses its uncalibrated 0.5 threshold, so those gate points are not a matched-coverage comparison. `reports/ood-comparison.json` includes confusion counts, balanced accuracy, a paired problem-bootstrap interval on the CriticLeanBench accuracy change, and source strata. `reports/ood-predictions.json` retains per-example scores without benchmark text.

## Frozen release: lean-fidelity-v1

`frozen-model.json` locks checkpoint 250, the base revision, every adapter/tokenizer file hash, data split hashes, and the existing calibration. Weights remain in the local run directory and Modal volume listed in that manifest; Git contains the release manifest, not the model binaries. Do not overwrite this release or retune its thresholds. Future training must produce a new version.

`frozen_model.py` verifies the saved files and loads the pinned backbone and adapter for inference, with all parameters frozen. Call `load_frozen(adapter_path)` in the pinned project environment. It returns `(model, tokenizer, calibration)`; wrap scoring in `torch.inference_mode()`. This prevents gradient updates through this loader, not deliberate file edits by other tools.

## Modal inference API

`modal_api.py` exposes the frozen **classifier**, not a Lean code generator. `POST` accepts `problem`, `lean_context`, and `candidate` strings. The response contains the raw logit, calibrated probability, `fidelity_decision` (`accept` or `review`), reason, release identifier, and hash of all three input strings. `lean_checked` is always false: the API does not execute Lean. The orchestration backend must independently check elaboration and combine that result with this score before approving a specification.

Inputs exceeding 4,096 tokens return review with null scores; nothing is silently truncated. Empty fields and oversized fields return HTTP 422. The endpoint requires Modal proxy authentication before a GPU can start. Keep `Modal-Key` and `Modal-Secret` in the application backend, never in the browser or repository. The GPU scales to zero after 30 idle seconds, with one A100 container maximum; cold starts will take longer than warm requests. Each scoring invocation has a 180-second timeout. This is a serving deployment, not the earlier bounded training job; repeated authorized requests can incur ongoing usage.

```sh
uv run --no-project --python 3.11 --with 'modal>=1.0,<2' python -m modal run --profile arin06 --env main modal_api.py
uv run --no-project --python 3.11 --with 'modal>=1.0,<2' python -m modal deploy --profile arin06 --env main modal_api.py
```

Required UI integration: English input → generative Lean writer → isolated Lean elaboration → this fidelity API → explicit approval/review → algorithm search. The sequence-classification adapter has no trained text-generation head and must not be presented as our fine-tuned Lean writer. Use a separately configured generative model for that node. The UI should show independent generation, elaboration, and fidelity states; a successful API call alone never means verified mathematics.

Example request from a backend (the three environment variables are deployment configuration):

```sh
curl --fail-with-body "$FIDELITY_API_URL" \
  -H "Modal-Key: $MODAL_PROXY_KEY" \
  -H "Modal-Secret: $MODAL_PROXY_SECRET" \
  -H 'Content-Type: application/json' \
  --data '{"problem":"Every Boolean ring is commutative.","lean_context":"import Mathlib","candidate":"theorem dummy {R : Type*} [Ring R] (h : ∀ a : R, a ^ 2 = a) : ∀ a b : R, a * b = b * a"}'
```

Modal proxy tokens are separate from the Modal CLI credentials used for deployment. Create one in the workspace dashboard or via `modal workspace proxy-tokens`; do not send the secret to the frontend. Authentication is documented at https://modal.com/docs/guide/webhook-proxy-auth.
