# M5-D dev-set retrieval experiment

This run retrieved the dev set only. It did not call the generation API and did not read the holdout. The retrieval input is `data/evaluation/inputs/m5_dev.questions.jsonl`, and each line contains only `id` and `question`. Reference answers, required facts, citations, and answerability stay in `data/evaluation/m5_dev.json` and are joined by `id` at scoring time.

All 15 questions were retrieved successfully. The coverage denominator is the 12 answerable questions and their 18 gold quotes. The three unanswerable questions, `m5_dev_003`, `m5_dev_006`, and `m5_dev_015`, have saved raw candidates and evidence bundles. They are excluded from Hit, Recall, Complete, MRR, and document hit rate below.

## Run settings

Fixed parameters: `candidate_k=30`, `rrf_constant=60`, and an evidence budget of 1024. The budget uses the M4 embedding tokenizer, which is separate from the generation-model tokenizer. The local corpus is `.local-m4`: 3152 documents. Strategies A, B, and C contain 17015, 15914, and 16432 chunks.

The comparison covers 3 chunking strategies, 3 retrieval modes, 3 values of k, and 2 packing policies: 54 replayable directories under `m5_runs/d_dev_retrieval/`. M4 ranks 30 candidates and then keeps the first k. Each question, strategy, and mode therefore had one live search, returning the top 10 chunks. k=3 and k=5 are prefixes of that ranking. All 135 searches are real index queries. Both packing policies are then applied to the same prefix, so the raw-candidate metrics do not change with the packing policy.

The script is `scripts/m6_evaluation/run_dev_retrieval_grid.py`. Raw coverage, post-budget coverage, mean kept chunks, mean context tokens, and per-mode latency are in `results/m5/d_dev_retrieval/summary.json`, under `conditions` and `latency`. The three-stage comparison is in `results/m5/d_dev_retrieval/three_stage_summary.json`, and the offline pass is in `results/m5/d_dev_retrieval/offline_summary.json`. The 54 directories stay local under `m5_runs/d_dev_retrieval/`. `.gitignore` excludes `m5_runs/`, so that tree is not in this repository. The question-file and gold hashes are the `files` entries in `data/evaluation/m5_dataset_manifest.json`.

## Metrics

A gold quote is covered when at least one returned chunk from that evidence document contains the quote in full. The full index of every strategy contains all 18 quotes (18/18), so the misses below come from ranking or the 1024-token budget. They do not come from a quote being split across chunks.

All metrics are macro averages over the 12 answerable questions:

- **Hit@k**: number of questions with at least one covered quote.
- **Evidence Recall@k**: for each question, covered quotes divided by that question's quotes, then averaged over 12 questions.
- **Complete@k**: number of questions whose quotes are all covered.
- **MRR@k**: reciprocal rank of the first chunk that covers any quote; 0 when none of the k chunks does.
- **Document hit rate**: number of questions whose gold-evidence document appears in the results.

Raw candidates are `retrieval.results`. Post-budget evidence is `selected_chunk_ids`, in the order packed into the evidence bundle. The 12 questions come from 6 events, and questions from the same event are related. The counts are reported as counts. They are evidence coverage, not final-answer correctness.

## Raw candidates

Each retrieval setting is one `conditions` entry in `results/m5/d_dev_retrieval/summary.json`. The `raw` object holds Hit, Recall, Complete, MRR, document hit, and the incomplete question ids. Raw metrics are identical for the two packing policies, so each strategy, mode, and k appears twice in that file with the same `raw` values.

Chunking: B with BM25 and B with Hybrid cover all 18 quotes at k=3. C with BM25 and C with Hybrid reach the same raw Complete at k=5. A with Dense remains 10/12 at k=10: the gold document for `m5_dev_004` is outside the top 10, and the second quote of `m5_dev_002` is also outside the top 10.

Retrieval mode: on strategy C at k=5, BM25 and Hybrid both have raw Complete 12/12, and Dense has 11/12. Hybrid MRR on A is 0.806, lower than BM25 on the same questions (0.903). The document is already hit, while the first covering chunk is ranked further down.

k: MRR does not change with k, because the first hit is inside the top 3. Increasing k adds the second quote when it is ranked further down. The main affected item is `m5_dev_002`, followed by `m5_dev_009` under B/Dense.

## Post-budget evidence

A 1024-token evidence bundle keeps about 3 chunks on average and uses about 860–950 tokens. Raising k from 5 to 10 can make the raw list complete while the post-budget coverage stays the same.

The five coverage metrics agree across both packing policies on all 27 retrieval settings. The difference is how many chunks are kept: in 22 of 324 answerable rows, the new policy keeps one extra chunk. `legacy_break_v1` stops at the first chunk that does not fit. `skip_continue_dedup_v1` skips that chunk and continues. For A/Dense/k=5 on `m5_dev_004`, the old policy stops after an oversized chunk and keeps 2 chunks, 675 tokens. The new policy keeps a later chunk that still fits, giving 3 chunks and 900 tokens. The extra chunk does not contain a still-missing gold quote, so Hit, Recall, Complete, MRR, and document hit stay the same.

The settings that lose coverage after the budget are the `conditions` whose `budget` object is lower than `raw`. Every other setting keeps the same five coverage metrics as its raw candidates. The same comparison, including which questions the budget newly drops, is in `results/m5/d_dev_retrieval/three_stage_summary.json`.

Under B/Dense/k=5, `m5_dev_002` is already incomplete in the raw candidates. The budget newly drops `m5_dev_009`. After the budget, the incomplete questions are 002 and 009. At k=10 both are complete in the raw list, and the budget drops both.

`m5_dev_002` is the main bottleneck. Under C/Hybrid/k=5, the second quote is raw rank 5, but appending it would take 1207 tokens, above 1024. Neither policy keeps it. Raw Complete is therefore 12/12 and post-budget Complete is 11/12. Under B/BM25 and B/Hybrid at k=3, both quotes are already in the top 3 and both fit in the budget, so post-budget Complete remains 12/12.

Mean kept chunks and mean context tokens on the answerable questions are `budget.mean_count` and `budget.mean_context_tokens` in each `conditions` entry. Compare the two `packing_policy` values for the same strategy, mode, and k.

## Retrieval latency

The per-mode search times are the `latency` object in `results/m5/d_dev_retrieval/summary.json`, and again under `retrieval.stored_latency` in `results/m5/d_dev_retrieval/offline_summary.json`. Each value is `timing_ms` for one live search across 15 questions. It includes query encoding and index lookup. It excludes model load and the first build of the BM25 vocabulary. Dense encoding has a median of about 5–6 ms. BM25 does not encode a query vector. Hybrid is the slowest, with a median of about 30–37 ms and p95 below 50 ms. k and the packing policy do not change this search time, because the search depth is fixed at 30 candidates. The whole grid process took 23.1 seconds, including index checks, offline model load, 135 searches, and writing 54 directories.

## How results are linked

The 15 dev ids match the gold ids one to one. `results.jsonl` in each A run points to that question's evidence bundle by the same `id` and records the file path and SHA-256. All 54 directories have status `COMPLETE` and pass the generation-side `load_a_run(max_items=15)` checks for the manifest hash, evidence hash, and packing binding.

One directory ready for reuse is `m5_runs/d_dev_retrieval/C_hybrid_k5_skip`:

- Configuration: strategy C, Hybrid, k=5, `candidate_k=30`, `skip_continue_dedup_v1`, 1024 tokens.
- SHA-256 of `results.jsonl`: `15d8e6b369c24c2bfcc3f73d2ad3159449df83768d0af07ee88ed64829ceb9ee`.
- First row `id=m5_dev_001`, file `item_0001/retrieval.json`, hash `b475c45c444ba02c1cfc12b8ad9a52f2103f2d14300fd47072849edfa56ad4dd`.
- Packing audit for the same item: `item_0001/packing.json`, hash `ba71d9b12de01a3aa01707aeaca2789aae2dbfd369c4d7d34504d986cdcb9740`.

These directories do not yet have `predictions.jsonl`. The generation-side link was checked on the earlier two-question G2 smoke run, `m5_runs/b_2db23a0069f644b0b69afa5728db6ce3`. Its `run.json` records the reused A run `m5_runs/b_38d3523a4c7044f39cecd196586484fc/retrieval/run.json`, with A-run SHA-256 `be3d27915a102ef7d044e902a7a71afcfffab8d49305dd3aa1a7a29491a38eba`. `predictions.jsonl` joins back to the question by `id` and gives `pipeline_file` plus `pipeline_sha256`. Both file hashes match the records in that `predictions.jsonl`.

`item_0001/pipeline.json` keeps the evidence chunks, the evidence-object hash, the first generation and review, one repair generation and review, and the final answer. That smoke set is a different question set from this dev set. It shows the link and is not part of the retrieval coverage above.

Later generation can replay any of the new directories without retrieving again. The current entry point runs the G2 pipeline. The dev set has 15 questions, so `--max-items` must be set to 15; the default of 10 truncates the batch. G0 and G1 do not yet have a separate accepted switch. Reuse the same evidence bundle, and let the corresponding evaluation driver record facts that were not cited. The command below documents the entry point. It was not executed in this run:

```bash
.venv_m5/bin/python -B -X utf8 -m scripts.m5_generation.b_cli \
  --retrieval-run m5_runs/d_dev_retrieval/C_hybrid_k5_skip \
  --budget-profile configs/m5_budget_cityu_cs5351.json \
  --max-items 15 \
  --output-dir m5_runs/b_dev_C_hybrid_k5_skip \
  --generate
```

## Limits to report with these results

- The denominator is the 12 answerable dev questions. The three unanswerable questions were retrieved and saved, and they are outside the coverage rates.
- The holdout was not used. These results can go into the retrieval section. They are not a final generalisation score.
- All 18 quotes fit inside a complete chunk under every strategy. Coverage differences come from ranking and the 1024-token budget.
- The new packing policy keeps extra chunks. On these 12 questions it does not raise the five coverage metrics.
- Questions are grouped into 6 events, so the counts should not be read as an advantage on independent samples.
- This run did not generate answers and did not apply human scoring.

## Offline reliability and statistics

Human scoring is not finished in this step. The rubric and the blank sheet were prepared so that M6 can fill them after answers exist. M6 is where those filled scores, the numerators and denominators, and the final report come together. This section only checks that the program handles bad inputs and that the summary script reads saved runs correctly. A passing offline test does not show that a live model can recognise a false fact. In the semantic cases, the judge verdict is supplied by the test.

The M5 offline suite, `python -m unittest discover -s tests -p 'test_m5*.py'`, passed 268 tests. The cases cover a forged citation, a wrong quote offset, an insufficient budget, a duplicate chunk, illegal input, transport and retrieval failure, the one-repair cap, and a missing price. With no pricing, `total_cost` stays unknown and is not written as zero. The checks are in `tests/test_m5*.py`.

`scripts/m6_evaluation/summarize_run.py` reads saved files only. It keeps the planned request count when a batch stops early and lists the unfinished requests separately. It rejects unknown question ids, required-fact ids that do not match the gold, and duplicate rows in the same run. It checks each prediction's pipeline path, SHA-256, and request id before adding that file to the token ledger. A path can be used once. A checkpoint call that has no prediction row, a missing manifest call count, or a count that does not match, leaves the batch total unknown and keeps the checked rows as a verified subtotal. The same file is counted once even when two prediction rows spell its path differently. For G1 and G2 it also reports citation coverage as CITED present facts over all present facts. `tests/test_m6_summary.py` covers those checks, plus p50/p95, an ERROR row remaining inside the all-request denominator, and a null cost staying null. The calibration sheet is excluded from the official score tally. When this ledger section was written, the dev sheet was blank, so the official count was 0/0. That 0/0 meant no official score had been entered. The dev G0/G1/G2 sheets are now filled. The current numbers are in `documents/m6/M6.md` and `../中文/M6_中文.md`. Holdout rows in those sheets remain unscored.

Applied to the two saved runs, the same figures are the `generation` list in `results/m5/d_dev_retrieval/offline_summary.json`. The smoke run used one repair. Its usage is complete, and its cost is still unknown because no verified price file was configured. The authentication failure remains 2/2 in the request count; the failed request is not dropped, and its missing usage is not turned into zero tokens or zero cost.

Retrieval latency was recomputed from the nine `k=10` new-policy directories, 135 question timings in total, because each of those directories stores one live search. Pooled across strategies and modes, p50 is 23.6 ms and p95 is 38.8 ms. Cite `latency` in `summary.json` for Dense, BM25, and Hybrid separately. The machine-readable copy of this offline pass is `results/m5/d_dev_retrieval/offline_summary.json`.

## M6 experiment plan

The matrix, run-manifest fields, freeze steps, and demo order are written in `documents/m6/M6_EXPERIMENT_PLAN.md`. The draft record is `configs/m6/experiment_plan_draft.json`, and `scripts/m6_evaluation/check_experiment_plan.py` checks it without a model call. `tests/test_m6_plan.py` passed.

The plan keeps the completed dev retrieval grid and names `m5_runs/d_dev_retrieval/C_hybrid_k5_skip` as the evidence bundle for a later protocol comparison. G2 remains the only accepted generation entry. G0 and G1 are specified for B and C: same questions, same evidence, and, after confirmation, the same model and budget. A dry run, a no-repair switch, or a G2 file with its review fields removed is not accepted as G0 or G1.

The sentences above describe the plan before dev generation. The current report is `documents/m6/M6.md`. The Chinese copy is `../中文/M6_中文.md`, outside this repository. The model and the per-call budget profile are frozen in `results/m6/freeze_20261122_dev_protocols.json`. The price is still unknown. Dev generation has been run and scored. The one saved holdout round is `m5_runs/m6_holdout_20261122T180540/`, and its scores are filled. It was not used for tuning. Commit `fa2fc97637bf5fbd41a8f3f9aefac6ad1dfb74eb` is an earlier base, not the freeze snapshot. The freeze snapshot is `ab0e6f73c17562bb04e5ffab71eee304f34fa3cc`. The freeze record sets `dev_run_precedes_freeze_commit` to true: it saves the files after the dev run and does not prove that every file at runtime matched that commit. Its holdout flags record the state when that file was written. Without `--manifest`, the checker validates the draft and the blank template. With `--manifest` pointing at the freeze file, or at `results/m6/m6_holdout_20261122T180540/manifest.json`, it validates that file too and, on success, reports that the draft check passed and the specified freeze manifest check passed. A frozen check also requires a clean working tree at the time the command runs.
