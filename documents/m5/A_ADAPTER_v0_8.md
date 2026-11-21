# A adapter v0.8: versioned packing and batch retrieval

This additive entry leaves Workshop.pack, the existing live entry, original M4 experiments and M5 generation unchanged. It never calls a generation API. It is not the B batch generation runner or a completed M6 evaluation.

## Interfaces

`scripts.m4_retrieval.packing.pack_response(response, tokenizer, token_budget, policy)` returns `(packed, audit)`. The existing four-field packed wrapper and retrieval_response.v2 stay unchanged. Version, exclusions, text offsets, source metadata conflicts and hashes live in a separate `packing.json` audit. `prepare_input(packed)` remains the M5 boundary.

`scripts.m4_retrieval.cli` accepts `--question` or `--input-jsonl`, with `--work-base` for live execution. A JSONL row accepts only `id`, `question` and optional `filters`. Evaluation gold fields are rejected, not sent to retrieval. IDs must be unique. Blank lines are ignored; malformed rows receive individual errors and other rows continue. Input is bounded to 5 MB / 1000 requests. IDs are never used as file paths. Every item gets a physical row number.

`--check-only` validates input/configuration without starting M4 or calling APIs. Live execution requires the existing Python 3.11 M4 environment and pinned cached assets. It initializes the model once and reuses it sequentially across questions. The initialization checks and runtime database restrictions are inherited from the existing worker.

The `configs/m4_m5.yaml` file uses the JSON subset of YAML; no YAML library is required. Keep that syntax when editing. Defaults remain Hybrid/C, k=5, candidate_k=30, RRF=60, 1024 embedding-model tokens and legacy packing. Override `--packing-policy skip_continue_dedup_v1` to deliberately use the new experimental policy. `--top-k` accepts 3/5/10 for later controlled development experiments; running these values alone is not an evaluation.

## Packing policies

- `legacy_break_v1`: matches the existing break-on-first-oversized behavior, without deduplication. Original code and records are preserved.
- `skip_continue_dedup_v1`: skips oversized chunks and considers later complete chunks. Deduplicates byte-identical text only within the same document and identical citation metadata. Duplicate chunk IDs are malformed input and rejected. Different sources or conflicting metadata are never merged away.

Every count uses the actual supplied M4 embedding tokenizer with truncation disabled, including source ID, title, URL and separators. This is not a generation-model count. M5 must still perform its own full-prompt budget check. No chunk text is shortened. A budget that fits no complete chunk produces an explicit EMPTY_SELECTED_CONTEXT adapter error while retaining the original OK retrieval candidates, never a knowledge refusal.

Source mappings use S labels in selected order. Offsets index the exact context text by Python Unicode code points, with exclusive ends. They are provisional M4 selection mappings; only the final M5 evidence may be cited. Metadata discrepancies for the same document are reported but not adjudicated. Semantic conflicts remain C's responsibility.

## Filters, errors and output

The new adapter explicitly rejects requested date filters with UNSUPPORTED_DATE_FILTER and all other nonempty filters with UNSUPPORTED_FILTER before retrieving. It does not silently ignore filters. The original Workshop filter support is unchanged.

Each new run directory contains run.json, results.jsonl and numbered item directories. Each live item contains retrieval.json (direct M5 input) and packing.json. Startup failures, invalid rows and retrieval exceptions remain errors. NO_EVIDENCE remains a distinct status. Results are flushed per item; an interrupted run is marked INTERRUPTED, never complete. There is no automatic retry or resume in this A entry. A future B runner must define recovery without silently duplicating paid calls.

## Local commands

Run from the project directory:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -p "test_m5_a_adapter.py" -v
.\.venv_m4\Scripts\python.exe -B -X utf8 -m scripts.m4_retrieval.cli --input-jsonl examples/m5/a_smoke_questions.jsonl --packing-policy skip_continue_dedup_v1 --check-only
.\.venv_m4\Scripts\python.exe -B -X utf8 -m scripts.m4_retrieval.cli --input-jsonl examples/m5/a_smoke_questions.jsonl --work-base "D:\Cityu SemA\CS5481\M4_work" --packing-policy skip_continue_dedup_v1
```

The supplied questions are smoke/development questions already seen in this project, not new held-out evaluation data. After a successful live run, pass each item's retrieval.json into the existing M5 pipeline CLI with --dry-run and export/check the selected evidence. No generation is needed for A acceptance.

## Remaining A acceptance

Offline tests do not replace real database/model verification. Verify the changed adapter and selection using the user's runtime. Record legacy/new policy differences on the same queries, candidates and budgets. A/D still need a genuinely new development set for k=3/5/10 comparisons; preserve historical M4 results. Do not claim improved answer quality from these smoke tests.
