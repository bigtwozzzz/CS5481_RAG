# M6 experiment plan, reproduction notes, and report frame

Status: the draft JSON checked by `check_experiment_plan.py` stays `not_frozen`. The freeze record for the code, prompts, per-call budget profile, and scoring guide is `results/m6/freeze_20261122_dev_protocols.json`. The dev G0/G1/G2 comparison has been run. There is still no verified price snapshot.

The machine-readable copy is `configs/m6/experiment_plan_draft.json`. The blank run record is `configs/m6/run_manifest.template.json`. `scripts/m6_evaluation/check_experiment_plan.py` reads both and makes no model call.

## What is already measured

The dev retrieval grid is complete: 15 questions, strategies A/B/C, Dense/BM25/Hybrid, k=3/5/10, and both packing policies. Holdout retrieval, generation, and scoring were not run, and the holdout was not used for tuning. Those retrieval numbers stay in `M5_D.md` and `m5_runs/d_dev_retrieval/summary.json`.

The planned generation control is the saved bundle `m5_runs/d_dev_retrieval/C_hybrid_k5_skip`: strategy C, Hybrid, k=5, `candidate_k=30`, `skip_continue_dedup_v1`, 1024 context tokens. `results.jsonl` SHA-256 is `15d8e6b369c24c2bfcc3f73d2ad3159449df83768d0af07ee88ed64829ceb9ee`. B/BM25 and B/Hybrid already cover all 12 answerable questions at k=3. That retrieval result does not choose the generation model.

Gold stays in `data/evaluation/m5_dev.json`. The file sent to retrieval or generation is `data/evaluation/inputs/m5_dev.questions.jsonl`, which contains `id` and `question` only.

## Experiment matrix

| Factor | Levels | What stays fixed | State |
| --- | --- | --- | --- |
| Retrieval | A/B/C, Dense/BM25/Hybrid, k=3/5/10, old and new packing | Dev questions, candidate_k=30, RRF 60, 1024 tokens | Completed, 0 generation calls |
| Protocol | G0, G1, G2 | Same 15 dev questions, the same evidence bundle, one model, one per-call budget profile | Dev generation completed. Tuning on the dev set stops |

One later sensitivity run may change a single retrieval factor after the gateway model is confirmed. The 54 retrieval directories are not a 54-run generation grid.

## Protocol driver to confirm with B and C

The current batch entry, `python -m scripts.m5_generation.b_cli --generate`, is the G2 path: structured generation, hard citation checks, automatic support review, and at most one shared repair. Prompts are `generation_v1.txt`, `repair_v1.txt`, and `support_v1.txt` (`m5-support-en-v0.10.1`). Their current hashes are in the draft plan. A reviewed pipeline remains G2 when `repair_used` is false. The saved smoke item `m5_runs/b_2db23a0069f644b0b69afa5728db6ce3/item_0001/pipeline.json` is G2. It uses a different question set and is not a dev score.

`scripts/m6_evaluation/protocol_driver.py` is the evaluation driver. It is not a switch on `b_cli`. G2 still calls `run_pipeline` with review and at most one repair. G0 loads `g0_prompt_citation_v1.txt`, which asks the model to cite inside the answer, and saves that text with no citation hard check, no review, and no repair. G1 loads `generation_v1.txt`, releases the draft only after structured hard citation validation, and does not review or repair. The same retrieval directory, question file, and model are the inputs for all three. Human scores still use `documents/m6/ANSWER_SCORING_v1.md`: G0 citation is `NOT_APPLICABLE`, and a correct uncited fact stays PRESENT.

`b_cli` still has no accepted G0 or G1 switch. The current generation prompt cannot be reused as G0.

These three runs must share the question file, the evidence bundle, the model, and the per-call budget profile. The 8192-token limit and 512-token margin apply to each call. They are not a shared total compute budget. Each run gets its own new output directory. The checker rejects three substitutions:

- a dry run, whose gate is `NOT_RUN`, is a local precheck;
- `--no-repair` still performs review on the single-question entry, and `b_cli` does not expose that flag;
- deleting review fields from a G2 pipeline leaves an unreviewed file, which is not an accepted G1 run.

`scripts/m6_evaluation/check_experiment_plan.py` implements that label check. `tests/test_m6_plan.py` covers the draft plan and the rejected shortcuts. `tests/test_m6_protocol.py` runs the three protocols on one offline fixture with a mock model.

## Run manifest

Copy `configs/m6/run_manifest.template.json` to `results/m6/<run_id>/manifest.json` when a run is actually started. Leave the template in place. Required fields:

| Field | What to record |
| --- | --- |
| `run_id`, `split`, `protocol` | New id, `dev` or `holdout`, and G0, G1, or G2 |
| `git_commit`, `working_tree_dirty` | Commit actually executed, and whether the tree was clean |
| `questions_sha256`, `gold_sha256` | Question file and gold file. `gold_sent_to_model` stays false |
| `corpus_sha256`, `index_manifest`, `embedding_revision` | Corpus and the A/B/C index manifest used |
| `retrieval_run`, `retrieval_run_sha256`, `results_sha256`, `retrieval_config` | The reused evidence bundle |
| `prompt_sha256` | Hashes of the prompt files this protocol actually loaded |
| `driver_accepted` | False until B and C accept a G0 or G1 driver |
| `model`, `budget_profile`, `budget_profile_sha256` | Filled only after gateway confirmation |
| `network_retries`, `pricing_file`, `pricing_sha256` | Retry cap and the verified price snapshot, when one exists |
| `output_dir`, `request_count`, `saved_predictions`, `unfinished_requests` | Planned count stays the denominator if the batch stops early |
| `api_requests`, `status`, `total_cost` | Physical calls, batch status, and cost. Unknown cost stays null |

The built-in budget profile `deepseek-flash` / `m5-token-budget-v0.5` stays in place. `configs/m5_budget_cityu_cs5351.json` is the frozen per-call profile for `CS5351/DeepSeek-V4-Flash`. The gateway model list did not return a context limit, so 8192 remains the application policy. The pricing template has null rates and cannot be passed to `--pricing-json`. Cost stays null.

## Freeze steps

1. Confirm the school gateway model id, the context limit, and that one small authenticated call succeeds. Do not print the key.
2. Record the model string returned by the provider. An alias is not a weight hash.
3. Choose or revise the additive budget profile. Keep the built-in `deepseek-flash` profile.
4. Copy `configs/m5_pricing.template.json` to a new snapshot, fill verified rates, currency, source URL, and `verified_at_utc`. Leave cost null when no snapshot exists.
5. Write `results/m6/freeze_<id>.json` from the manifest fields: clean commit, dataset hashes, index manifest, prompt hashes, evidence-bundle hash, model, budget hash, retry cap, and pricing hash.
6. The dev protocol comparison was run before this freeze record. It stays the dev result. Do not retune it. Later holdout work uses the frozen files.
7. Run the 25-question holdout only after the freeze record. Use the frozen questions, evidence settings, model, budget, and prompts once.
8. If any of those inputs changes after the holdout has been seen, report the exposure and start a new freeze id. The earlier holdout round is no longer an independent test.
9. Keep an interrupted ledger. The planned request count remains the denominator, and unfinished items are listed separately. Do not delete a failed run and replace it silently.

The current base commit is `fa2fc97637bf5fbd41a8f3f9aefac6ad1dfb74eb`, and the working tree is dirty. That commit is not a freeze snapshot. The checker refuses to mark the draft plan frozen, refuses a holdout manifest before a freeze record, and refuses a zero cost when no pricing hash is present.

## Reproduction commands

From the repository root. These commands do not call the gateway.

```bash
PYTHONPATH=".:tests" .venv_m5/bin/python -B -m unittest test_m6_plan test_m6_summary
.venv_m5/bin/python -B -m scripts.m6_evaluation.check_experiment_plan
```

The G2 dev command below is the accepted entry shape. It was not executed. `--max-items` must be 15. Run it only after the model, budget, and pricing decision, into a new directory:

```bash
.venv_m5/bin/python -B -X utf8 -m scripts.m5_generation.b_cli \
  --retrieval-run m5_runs/d_dev_retrieval/C_hybrid_k5_skip \
  --budget-profile configs/m5_budget_cityu_cs5351.json \
  --network-retries 0 \
  --max-items 15 \
  --output-dir m5_runs/b_dev_C_hybrid_k5_skip_g2 \
  --generate
```

Add `--pricing-json` only with a verified snapshot. The evaluation driver prints the shared controls and does not call the model:

```bash
.venv_m5/bin/python -B -m scripts.m6_evaluation.protocol_driver \
  --protocol G0 \
  --retrieval-run m5_runs/d_dev_retrieval/C_hybrid_k5_skip
```

Repeat the command with `--protocol G1` and `--protocol G2`. The dev comparison was then run with `--generate` into `m5_runs/m6_dev_protocols_20261122T165403/`. `b_cli` remains the G2 product entry and still has no protocol switch.

## Report frame

Fill every rate as numerator/denominator. `0/0` in the score table means no official score has been entered. ERROR stays in the all-request denominator. A second column excludes ERROR. Calibration rows stay out. The 12 answerable questions are the fact-coverage population. The 3 unanswerable questions stay in the request count and in the refusal counts.

| Section | Source | Current content |
| --- | --- | --- |
| Data | dataset manifest v1.1 | Dev 15 scored. Holdout generation and scoring not run |
| Retrieval | `M5_D.md` | Filled |
| Generation setup | `M6.md` | Dev run recorded. Per-call budget frozen. Price unknown |
| G0/G1/G2 quality | human score sheets | Filled for dev. Same labels: CORRECT 11/15, CORRECT_REFUSAL 3/15, PARTIAL 1/15 |
| Repair effect | paired final answers and `repair_used` | G2 repaired 1/15. Required-fact coverage did not change |
| Errors | pipeline `error.code`, kept in the denominator | Scored run 0/15. Separate network-failure batch kept out |
| Model latency, tokens, cost | `summarize_run.py` | Per-call latency and token totals filled. Cost null |
| Limits | `M6.md` | Review miss on `m5_dev_002`, citation denominator, and per-call budget |

Dev protocol table. Citation coverage of stated required facts is N/A for G0 and 25/25 for G1 and G2. Required-fact coverage for all three is 25/28. PARTIAL is 1/15. FACTUAL_ERROR, FALSE_REFUSAL, INCOMPLETE_REFUSAL, and NO_HIT are 0/15. CORRECT_REFUSAL is 3/15.

| Protocol | Requests | ERROR | CORRECT, all requests | CORRECT, excluding ERROR | Fact coverage | False refusal | Cost |
| --- | ---: | --- | --- | --- | --- | --- | --- |
| G0 | 15 | 0/15 | 11/15 | 11/15 | 25/28 | 0/15 | unknown |
| G1 | 15 | 0/15 | 11/15 | 11/15 | 25/28 | 0/15 | unknown |
| G2 | 15 | 0/15 | 11/15 | 11/15 | 25/28 | 0/15 | unknown |

For G1 and G2, citation coverage is the number of PRESENT facts marked `CITED` in `fact_citation_marks`, divided by the number of PRESENT facts. That denominator is 25 here, while required-fact coverage uses 28. `citation_support=FULL` remains the question-level label and is not that numerator. For G0, citation is `NOT_APPLICABLE`. A stored 0/0 is an empty denominator, not a citation rate of 0%, and it does not say the G0 answers contain no citations. Call-latency p50 and p95 are per API call. Batch wall time divided by 15 is a mean, not a per-question median. Retrieval latency is already reported separately and is not model-call latency. G2 passed `m5_dev_002` after reading the question as organisation plus year. The human label remains PARTIAL. COMPLETE, a verified ledger, and 0 check-script errors do not establish answer correctness.

## Demo order

1. Show that the dev JSONL has only `id` and `question`, and that the holdout manifest says sealed.
2. Show the retrieval table and the C/Hybrid/k=5 bundle hash.
3. Run `check_experiment_plan` and show that the draft JSON remains `not_frozen`. The freeze record is the separate file.
4. Show the filled dev score sheets. The holdout rows in those sheets are still blank.
5. Open one prediction, check `pipeline_sha256`, and show the final answer fields.
6. Show the numerator and denominator for one protocol, including the G2 review miss on `m5_dev_002`.
7. Holdout generation and scoring stay unrun. They were not used for tuning.

## Still waiting

Holdout generation and scoring wait until this freeze is left unchanged. A verified price snapshot is still absent, so cost stays unknown. The gateway did not return a context limit. Dev-set tuning stops. The dev comparison was run before the freeze commit; it is the recorded dev result, and it is not rerun to make the commit timestamp earlier.
