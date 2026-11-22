# M5-D dev-set retrieval experiment

This run retrieved the dev set only. It did not call the generation API and did not read the holdout. The retrieval input is `data/evaluation/inputs/m5_dev.questions.jsonl`, and each line contains only `id` and `question`. Reference answers, required facts, citations, and answerability stay in `data/evaluation/m5_dev.json` and are joined by `id` at scoring time.

All 15 questions were retrieved successfully. The coverage denominator is the 12 answerable questions and their 18 gold quotes. The three unanswerable questions, `m5_dev_003`, `m5_dev_006`, and `m5_dev_015`, have saved raw candidates and evidence bundles. They are excluded from Hit, Recall, Complete, MRR, and document hit rate below.

## Run settings

Fixed parameters: `candidate_k=30`, `rrf_constant=60`, and an evidence budget of 1024. The budget uses the M4 embedding tokenizer, which is separate from the generation-model tokenizer. The local corpus is `.local-m4`: 3152 documents. Strategies A, B, and C contain 17015, 15914, and 16432 chunks.

The comparison covers 3 chunking strategies, 3 retrieval modes, 3 values of k, and 2 packing policies: 54 replayable directories under `m5_runs/d_dev_retrieval/`. M4 ranks 30 candidates and then keeps the first k. Each question, strategy, and mode therefore had one live search, returning the top 10 chunks. k=3 and k=5 are prefixes of that ranking. All 135 searches are real index queries. Both packing policies are then applied to the same prefix, so the raw-candidate metrics do not change with the packing policy.

The script is `scripts/m6_evaluation/run_dev_retrieval_grid.py`. The machine-readable summary is `m5_runs/d_dev_retrieval/summary.json`.

| File | SHA-256 |
| --- | --- |
| Dev question JSONL | `868b4a198b4cce5570ab6c1d341e8ec641b0b95cff9fbe3ceeec71b96813751e` |
| Dev gold | `a9ef3d34d8d968eb545f7252b1a42da0ffbf3e24f1124d49e7e671cf96c04184` |

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

| Strategy | Mode | k | Hit@k | Recall@k | Complete@k | MRR@k | Document hit | Incomplete |
| --- | --- | ---: | --- | ---: | --- | ---: | --- | --- |
| A | Dense | 3 | 11/12 | 0.875 | 10/12 | 0.778 | 11/12 | 002, 004 |
| A | Dense | 5 | 11/12 | 0.875 | 10/12 | 0.778 | 11/12 | 002, 004 |
| A | Dense | 10 | 11/12 | 0.875 | 10/12 | 0.778 | 11/12 | 002, 004 |
| A | BM25 | 3 | 12/12 | 0.958 | 11/12 | 0.903 | 12/12 | 002 |
| A | BM25 | 5 | 12/12 | 1.000 | 12/12 | 0.903 | 12/12 | — |
| A | BM25 | 10 | 12/12 | 1.000 | 12/12 | 0.903 | 12/12 | — |
| A | Hybrid | 3 | 12/12 | 0.958 | 11/12 | 0.806 | 12/12 | 002 |
| A | Hybrid | 5 | 12/12 | 0.958 | 11/12 | 0.806 | 12/12 | 002 |
| A | Hybrid | 10 | 12/12 | 1.000 | 12/12 | 0.806 | 12/12 | — |
| B | Dense | 3 | 12/12 | 0.917 | 10/12 | 0.903 | 12/12 | 002, 009 |
| B | Dense | 5 | 12/12 | 0.958 | 11/12 | 0.903 | 12/12 | 002 |
| B | Dense | 10 | 12/12 | 1.000 | 12/12 | 0.903 | 12/12 | — |
| B | BM25 | 3 | 12/12 | 1.000 | 12/12 | 0.903 | 12/12 | — |
| B | BM25 | 5 | 12/12 | 1.000 | 12/12 | 0.903 | 12/12 | — |
| B | BM25 | 10 | 12/12 | 1.000 | 12/12 | 0.903 | 12/12 | — |
| B | Hybrid | 3 | 12/12 | 1.000 | 12/12 | 0.903 | 12/12 | — |
| B | Hybrid | 5 | 12/12 | 1.000 | 12/12 | 0.903 | 12/12 | — |
| B | Hybrid | 10 | 12/12 | 1.000 | 12/12 | 0.903 | 12/12 | — |
| C | Dense | 3 | 12/12 | 0.958 | 11/12 | 0.889 | 12/12 | 002 |
| C | Dense | 5 | 12/12 | 0.958 | 11/12 | 0.889 | 12/12 | 002 |
| C | Dense | 10 | 12/12 | 1.000 | 12/12 | 0.889 | 12/12 | — |
| C | BM25 | 3 | 12/12 | 0.958 | 11/12 | 0.903 | 12/12 | 002 |
| C | BM25 | 5 | 12/12 | 1.000 | 12/12 | 0.903 | 12/12 | — |
| C | BM25 | 10 | 12/12 | 1.000 | 12/12 | 0.903 | 12/12 | — |
| C | Hybrid | 3 | 12/12 | 0.958 | 11/12 | 0.903 | 12/12 | 002 |
| C | Hybrid | 5 | 12/12 | 1.000 | 12/12 | 0.903 | 12/12 | — |
| C | Hybrid | 10 | 12/12 | 1.000 | 12/12 | 0.903 | 12/12 | — |

Question ids omit the `m5_dev_` prefix. Raw metrics are identical for the two packing policies, so each retrieval setting appears once.

Chunking: B with BM25 and B with Hybrid cover all 18 quotes at k=3. C with BM25 and C with Hybrid reach the same raw Complete at k=5. A with Dense remains 10/12 at k=10: the gold document for `m5_dev_004` is outside the top 10, and the second quote of `m5_dev_002` is also outside the top 10.

Retrieval mode: on strategy C at k=5, BM25 and Hybrid both have raw Complete 12/12, and Dense has 11/12. Hybrid MRR on A is 0.806, lower than BM25 on the same questions (0.903). The document is already hit, while the first covering chunk is ranked further down.

k: MRR does not change with k, because the first hit is inside the top 3. Increasing k adds the second quote when it is ranked further down. The main affected item is `m5_dev_002`, followed by `m5_dev_009` under B/Dense.

## Post-budget evidence

A 1024-token evidence bundle keeps about 3 chunks on average and uses about 860–950 tokens. Raising k from 5 to 10 can make the raw list complete while the post-budget coverage stays the same.

The five coverage metrics agree across both packing policies on all 27 retrieval settings. The difference is how many chunks are kept: in 22 of 324 answerable rows, the new policy keeps one extra chunk. `legacy_break_v1` stops at the first chunk that does not fit. `skip_continue_dedup_v1` skips that chunk and continues. For A/Dense/k=5 on `m5_dev_004`, the old policy stops after an oversized chunk and keeps 2 chunks, 675 tokens. The new policy keeps a later chunk that still fits, giving 3 chunks and 900 tokens. The extra chunk does not contain a still-missing gold quote, so Hit, Recall, Complete, MRR, and document hit stay the same.

The rows below lose coverage after the budget. Every other setting keeps the same five coverage metrics as its raw candidates.

| Strategy | Mode | k | Post-budget Recall | Post-budget Complete | Dropped by the budget |
| --- | --- | ---: | ---: | --- | --- |
| A | BM25 | 5, 10 | 0.958 | 11/12 | 002 |
| A | Hybrid | 10 | 0.958 | 11/12 | 002 |
| B | Dense | 5 | 0.917 | 10/12 | 009 |
| B | Dense | 10 | 0.917 | 10/12 | 002, 009 |
| C | Dense | 10 | 0.958 | 11/12 | 002 |
| C | BM25 | 5, 10 | 0.958 | 11/12 | 002 |
| C | Hybrid | 5, 10 | 0.958 | 11/12 | 002 |

Under B/Dense/k=5, `m5_dev_002` is already incomplete in the raw candidates. The budget newly drops `m5_dev_009`. After the budget, the incomplete questions are 002 and 009. At k=10 both are complete in the raw list, and the budget drops both.

`m5_dev_002` is the main bottleneck. Under C/Hybrid/k=5, the second quote is raw rank 5, but appending it would take 1207 tokens, above 1024. Neither policy keeps it. Raw Complete is therefore 12/12 and post-budget Complete is 11/12. Under B/BM25 and B/Hybrid at k=3, both quotes are already in the top 3 and both fit in the budget, so post-budget Complete remains 12/12.

Mean kept chunks and mean context tokens on the answerable questions:

| Strategy | Mode | k | Legacy chunks | Legacy tokens | New-policy chunks | New-policy tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| A | Dense | 3 | 2.75 | 860.8 | 2.75 | 860.8 |
| A | Dense | 5 | 2.75 | 860.8 | 3.00 | 928.3 |
| A | Dense | 10 | 2.75 | 860.8 | 3.00 | 928.3 |
| A | BM25 | 3 | 2.92 | 893.7 | 2.92 | 893.7 |
| A | BM25 | 5 | 3.00 | 910.7 | 3.08 | 936.9 |
| A | BM25 | 10 | 3.00 | 910.7 | 3.08 | 936.9 |
| A | Hybrid | 3 | 2.92 | 909.2 | 2.92 | 909.2 |
| A | Hybrid | 5 | 2.92 | 909.2 | 3.00 | 933.6 |
| A | Hybrid | 10 | 2.92 | 909.2 | 3.08 | 950.6 |
| B | Dense | 3 | 2.92 | 889.6 | 2.92 | 889.6 |
| B | Dense | 5 | 2.92 | 889.6 | 3.08 | 938.9 |
| B | Dense | 10 | 2.92 | 889.6 | 3.08 | 938.9 |
| B | BM25 | 3 | 3.00 | 902.6 | 3.00 | 902.6 |
| B | BM25 | 5 | 3.00 | 902.6 | 3.00 | 902.6 |
| B | BM25 | 10 | 3.00 | 902.6 | 3.08 | 919.1 |
| B | Hybrid | 3 | 3.00 | 891.4 | 3.00 | 891.4 |
| B | Hybrid | 5 | 3.08 | 913.9 | 3.08 | 913.9 |
| B | Hybrid | 10 | 3.08 | 913.9 | 3.17 | 927.2 |
| C | Dense | 3 | 3.00 | 879.9 | 3.00 | 879.9 |
| C | Dense | 5 | 3.00 | 879.9 | 3.00 | 879.9 |
| C | Dense | 10 | 3.00 | 879.9 | 3.17 | 908.6 |
| C | BM25 | 3 | 2.92 | 888.4 | 2.92 | 888.4 |
| C | BM25 | 5 | 2.92 | 888.4 | 3.00 | 903.3 |
| C | BM25 | 10 | 2.92 | 888.4 | 3.00 | 903.3 |
| C | Hybrid | 3 | 3.00 | 883.7 | 3.00 | 883.7 |
| C | Hybrid | 5 | 3.00 | 883.7 | 3.00 | 883.7 |
| C | Hybrid | 10 | 3.00 | 883.7 | 3.08 | 897.2 |

## Retrieval latency

The table is `timing_ms` for one live search across 15 questions. It includes query encoding and index lookup. It excludes model load and the first build of the BM25 vocabulary. Dense encoding has a median of about 5–6 ms. BM25 does not encode a query vector. Hybrid is the slowest, with a median of about 30–37 ms and p95 below 50 ms. k and the packing policy do not change this search time, because the search depth is fixed at 30 candidates.

| Strategy | Mode | Questions | Encode p50 | Search p50 | Total p50 | Total p95 | Total mean |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | Dense | 15 | 6.0 | 5.6 | 12.3 | 18.8 | 13.5 |
| A | BM25 | 15 | 0.0 | 25.5 | 26.5 | 32.2 | 25.9 |
| A | Hybrid | 15 | 5.3 | 30.6 | 36.9 | 47.2 | 36.4 |
| B | Dense | 15 | 4.8 | 6.4 | 12.2 | 17.7 | 12.4 |
| B | BM25 | 15 | 0.0 | 21.6 | 23.2 | 43.3 | 25.5 |
| B | Hybrid | 15 | 5.0 | 23.7 | 29.7 | 34.9 | 29.1 |
| C | Dense | 15 | 4.6 | 6.3 | 11.9 | 16.7 | 12.5 |
| C | BM25 | 15 | 0.0 | 22.6 | 23.6 | 42.1 | 25.5 |
| C | Hybrid | 15 | 5.0 | 24.7 | 30.4 | 35.8 | 29.9 |

Times are milliseconds. The whole grid process took 23.1 seconds, including index checks, offline model load, 135 searches, and writing 54 directories.

## How results are linked

The 15 dev ids match the gold ids one to one. `results.jsonl` in each A run points to that question's evidence bundle by the same `id` and records the file path and SHA-256. All 54 directories have status `COMPLETE` and pass the generation-side `load_a_run(max_items=15)` checks for the manifest hash, evidence hash, and packing binding.

One directory ready for reuse is `m5_runs/d_dev_retrieval/C_hybrid_k5_skip`:

- Configuration: strategy C, Hybrid, k=5, `candidate_k=30`, `skip_continue_dedup_v1`, 1024 tokens.
- SHA-256 of `results.jsonl`: `15d8e6b369c24c2bfcc3f73d2ad3159449df83768d0af07ee88ed64829ceb9ee`.
- First row `id=m5_dev_001`, file `item_0001/retrieval.json`, hash `b475c45c444ba02c1cfc12b8ad9a52f2103f2d14300fd47072849edfa56ad4dd`.
- Packing audit for the same item: `item_0001/packing.json`, hash `ba71d9b12de01a3aa01707aeaca2789aae2dbfd369c4d7d34504d986cdcb9740`.

These directories do not yet have `predictions.jsonl`. The generation-side link was checked on the earlier two-question G2 smoke run, `m5_runs/b_2db23a0069f644b0b69afa5728db6ce3`. Its `run.json` records the reused A run `m5_runs/b_38d3523a4c7044f39cecd196586484fc/retrieval/run.json`, with A-run SHA-256 `be3d27915a102ef7d044e902a7a71afcfffab8d49305dd3aa1a7a29491a38eba`. `predictions.jsonl` joins back to the question by `id` and gives `pipeline_file` plus `pipeline_sha256`. Both file hashes match the records:

| id | Status | pipeline.json | SHA-256 |
| --- | --- | --- | --- |
| a-smoke-eris | ANSWERED | item_0001/pipeline.json | `138ea5c9c6ba6c0410be62218173769a6cf4ee6340d6175c76e6d27cb44afce5` |
| a-smoke-passports | INSUFFICIENT_SOURCES | item_0002/pipeline.json | `7aa5f69f8b93ff2a0eb2a5f80c5bdfd1a53a8c11beb3c8ee833ee25f84274876` |

`item_0001/pipeline.json` keeps the evidence chunks, the evidence-object hash, the first generation and review, one repair generation and review, and the final answer. That smoke set is a different question set from this dev set. It shows the link and is not part of the retrieval table above.

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

The M5 offline suite, `python -m unittest discover -s tests -p 'test_m5*.py'`, passed 268 tests. The cases below were run again individually and passed.

| Behaviour | What the test checks | Result |
| --- | --- | --- |
| Forged citation | A forged URL or an unknown source id is rejected locally, before a model call | Pass |
| Wrong offset | A quote whose character span does not match the source is rejected | Pass |
| Insufficient budget | One token over the limit fails; an unfit top chunk stops before any API call; review overflow keeps the evidence and makes zero calls | Pass |
| Duplicate chunk | Duplicate selected ids and duplicate chunk ids are rejected | Pass |
| Illegal input | Malformed JSON, duplicate keys, preview or error inputs, and invalid CLI options fail closed | Pass |
| Failure | Transport retry exhaustion and a retrieval error stay technical errors | Pass |
| Repair cap | One shared content repair is allowed; a second JSON failure stops at two calls and does not release an answer | Pass |
| Missing price | With no pricing, `total_cost` stays unknown. It is not written as zero | Pass |

`scripts/m6_evaluation/summarize_run.py` reads saved files only. It keeps the planned request count when a batch stops early and lists the unfinished requests separately. It rejects unknown question ids, required-fact ids that do not match the gold, and duplicate rows in the same run. It checks each prediction's pipeline path, SHA-256, and request id before adding that file to the token ledger. A path can be used once. A checkpoint call that has no prediction row, a missing manifest call count, or a count that does not match, leaves the batch total unknown and keeps the checked rows as a verified subtotal. The same file is counted once even when two prediction rows spell its path differently. For G1 and G2 it also reports citation coverage as CITED present facts over all present facts. `tests/test_m6_summary.py` covers those checks, plus p50/p95, an ERROR row remaining inside the all-request denominator, and a null cost staying null. The calibration sheet is excluded from the official score tally. When this ledger section was written, the dev sheet was blank, so the official count was 0/0. That 0/0 meant no official score had been entered. The dev G0/G1/G2 sheets are now filled. The current numbers are in `M6.md` and `M6_中文.md`. Holdout rows in those sheets remain unscored.

Applied to the saved runs, the script reports:

| Run | Requests | ERROR kept in the denominator | API calls | Input tokens | Output tokens | Call latency p50 / p95 | `total_cost` |
| --- | ---: | --- | ---: | ---: | ---: | --- | --- |
| G2 smoke `b_2db23a0069f644b0b69afa5728db6ce3` | 2 | 0/2 | 6 | 16000 | 1111 | 2999.0 / 4310.7 ms | null, `pricing_not_configured` |
| Failed authentication `b_03f9550560a243e18cca42fbeb924abe` | 2 | 2/2 | 1 | unknown | unknown | 1741.2 / 1741.2 ms | null, `pricing_not_configured` |

The smoke run used one repair. Its usage is complete, and its cost is still unknown because no verified price file was configured. The authentication failure remains 2/2 in the request count; the failed request is not dropped, and its missing usage is not turned into zero tokens or zero cost.

Retrieval latency was recomputed from the nine `k=10` new-policy directories, 135 question timings in total, because each of those directories stores one live search. Pooled across strategies and modes, p50 is 23.6 ms and p95 is 38.8 ms. The per-mode table above remains the one to cite for Dense, BM25, and Hybrid separately. The machine-readable copy is `m5_runs/d_dev_retrieval/offline_summary.json`.

## M6 experiment plan

The matrix, run-manifest fields, freeze steps, and demo order are written in `documents/m6/M6_EXPERIMENT_PLAN.md`. The draft record is `configs/m6/experiment_plan_draft.json`, and `scripts/m6_evaluation/check_experiment_plan.py` checks it without a model call. `tests/test_m6_plan.py` passed.

The plan keeps the completed dev retrieval grid and names `m5_runs/d_dev_retrieval/C_hybrid_k5_skip` as the evidence bundle for a later protocol comparison. G2 remains the only accepted generation entry. G0 and G1 are specified for B and C: same questions, same evidence, and, after confirmation, the same model and budget. A dry run, a no-repair switch, or a G2 file with its review fields removed is not accepted as G0 or G1.

The sentences above describe the plan before dev generation. The current report is `M6.md`, with the Chinese copy in `M6_中文.md`. The model and the per-call budget profile are frozen in `results/m6/freeze_20261122_dev_protocols.json`. The price is still unknown. Dev generation has been run and scored. Holdout generation and scoring were not run and were not used for tuning. Commit `fa2fc97637bf5fbd41a8f3f9aefac6ad1dfb74eb` is not the freeze snapshot. The freeze record sets `dev_run_precedes_freeze_commit` to true: it saves the files after the run and does not prove that every file at runtime matched that commit. The draft-plan checker still prints that the draft is not frozen. That line describes the draft file, not a failed freeze.
