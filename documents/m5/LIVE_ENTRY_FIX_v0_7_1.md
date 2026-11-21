# Live-entry BM25 initialization fix v0.7.1

The first user run of v0.7 reached the existing model and collection checks but failed in Hybrid retrieval with `BM25_NOT_READY`: `Call build_bm25() before lexical or hybrid retrieval`. The notebook integration-check cell had previously prepared BM25, but a fresh CLI worker had not. This was an initialization omission in the new entry, not a dependency or data installation failure.

The worker now calls the existing `Workshop.build_bm25()` before BM25 or Hybrid retrieval. This builds missing A/B/C in-memory lexical indices and reuses existing ones. Dense-only retrieval does not build BM25. No retrieval, ranking or packing algorithm is replaced. If M4 returns an error, its original code and message are also printed by the worker.

Install this patch after v0.7. It updates only `scripts/m5_live/retrieval_worker.py` and adds this note plus the regression test. Existing files are hash-checked and backed up before replacement. Failed-run records, M4 implementation, source data, environments, prompts and historical answers are preserved.

After installation, rerun the same zero-API command in the project root:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.m5_live.cli --work-base "D:\Cityu SemA\CS5481\M4_work" --question "Which celestial body prompted the 2006 vote on Pluto?" --dry-run
```

Expect `BM25 ready: A`, `BM25 ready: B`, `BM25 ready: C`, then a retrieval result. For the demonstration question, the acceptance target is `Live retrieval status: OK`, `Unified status: READY_FOR_PIPELINE`, `DeepSeek API calls: 0`, and `Local contract checks: PASS`. A new run directory is created; the failed run is not rewritten. This dry-run does not generate an answer or request a key.

The new regressions first reproduce the original missing-index error, then exercise the actual M4 BM25, RRF, packing and schema-validation code for all three strategies. Only the collection backend and embedding vectors are small fixtures. Tests also cover dense-only behavior, index reuse, build failure and lexical no-match. They are stronger boundary regressions than the mocked retrieval in the original bridge tests, but they do not replace a real-database acceptance run.

The developer session still cannot launch the user's Python 3.11 executable. Full live acceptance of this patch remains pending the user's PowerShell run. No paid API calls are needed for installation or acceptance. Existing `run.json` orchestrator version stays v0.7 because that module is unchanged; this patch is recorded in the installer update manifest/log and this note.
