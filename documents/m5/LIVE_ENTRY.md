# Single-question live entry v0.7

This additive entry coordinates the existing M4 Workshop and M5 pipeline in separate Python processes. It reuses the pinned M4 database/model and the existing M5 prompts, repair policy and token budget. There are no dependency changes. M4 runs in `.venv_m4` (Python 3.11, Chroma 1.5.9); M5 runs in `.venv` with tokenizers 0.22.2. Jinja2 is not required by the M5 production budget implementation. Both interpreters are configurable by explicit paths.

## First run: no API calls

Run from the project root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.m5_live.cli --work-base "D:\Cityu SemA\CS5481\M4_work" --question "Which celestial body prompted the 2006 vote on Pluto?" --dry-run
```

The command checks the two interpreters and local paths, loads the cached embedding model and existing runtime database, retrieves and packs evidence, runs the M5 budget preflight, and exports the public contracts. It does not request a key or call DeepSeek. Omitting both `--dry-run` and `--generate` also chooses this zero-API mode.

Expected final status for this demonstration question: `READY_FOR_PIPELINE`, `Live retrieval completed: true`, `DeepSeek API calls: 0`, and `Local contract checks: PASS`. The newly retrieved evidence can differ if runtime data changes; investigate differences rather than forcing a result. No answer is generated in this mode.

For a shorter dependency/path-only check, use `--check-only` instead of the question and `--dry-run`. It returns `ENVIRONMENT_READY` without opening Chroma or loading the embedding model. Passing that check does not prove live retrieval works.

The default work-base layout is `m3_data`, `runtime_chroma` and `model_cache`. Use `--data-root` or `--run-db` if these paths differ. The initialized database must have its matching `.m4_copy_ready.json` marker; original M3 databases are refused. The command does not copy a missing database or download missing model files. Cached-model loading is forced offline. Chroma may maintain internal files in its runtime copy when it opens; the entry does not insert/update/delete collection records. Do not simultaneously run an index rebuild against that database.

## Generation after the live preflight succeeds

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.m5_live.cli --work-base "D:\Cityu SemA\CS5481\M4_work" --question "Which celestial body prompted the 2006 vote on Pluto?" --generate
```

This explicitly enables paid DeepSeek generation and review, with at most four API calls and one shared repair. `--no-repair` reduces the maximum to two calls. The existing hidden key prompt is inherited by the M5 subprocess; do not put a key in the question or command arguments. This version does not replace getpass with environment-only key management. Keys are not written into the new run records or sent to the M4 worker.

Every invocation creates a new run, including a new live retrieval. Generation does not resume a previous dry-run. No automatic rerun is performed after a process failure. Interrupting a paid call may leave the API outcome unknown: inspect `run.json` and the child pipeline checkpoint before retrying.

## Files and provenance

Each run creates `m5_runs/live_<id>/`:

| File | Meaning |
|---|---|
| `request.json` | Question, selected runtime paths and retrieval configuration |
| `m4_environment.json`, `m5_environment.json` | Interpreter and dependency checks |
| `m4_startup.json` | Index/model checks and live retrieval provenance |
| `retrieval.json` | Original Workshop v2 response, packed context and selected chunk IDs |
| `pipeline/pipeline.json` | Existing M5 stage/call/repair record; checkpoints survive many errors |
| `pipeline/answer.json` | Draft, only when produced by the existing pipeline |
| `contracts/` | Public contract export and summary after completed pipeline validation |
| `run.json` | Outer live-run status and hashes linking the child records |

Some files are absent when an earlier stage fails. Existing output directories are refused. The new entry checks question, config, index manifest and retrieval hashes across the boundary; public schema/export checks bind the completed M5 record. It does not execute a notebook or rewrite repository schemas. It uses inherited Workshop retrieval/packing with a small constructor adapter that avoids the notebook constructor's schema-write side effect.

The inner M5 adapter still reports `live_retrieval_executed=false`: that inner process reads a saved file. The outer `run.json` and `m4_startup.json` identify the retrieval performed immediately before it and bind the file hashes. This scope distinction is intentional. Hashes demonstrate consistency, not external source authenticity or proof of provider receipt.

The original M5 CLI may display an automatically accepted draft before the additional public-contract export finishes. A failed outer contract check marks the unified run ERROR; inspect the complete run before accepting its artifacts. Public export is an additional delivery check, not a replacement for the existing generation/review gates.

## Statuses, boundaries and limitations

- `READY_FOR_PIPELINE`: live retrieval and local checks completed, no answer generated.
- `ANSWERED`, `PARTIAL`, `INSUFFICIENT_SOURCES`: preserved from the reviewed M5 pipeline. Retrieved candidates do not prove answerability.
- `ERROR`: startup, retrieval, generation, review, process, binding or contract failure; never relabelled as insufficient evidence.
- `NO_EVIDENCE` retrieval is processed by the deterministic M5 refusal with zero API calls. A valid M4 ERROR is passed to M5 with dry-run forced and zero calls. A worker crash stops before M5.
- All accepted generated answers remain drafts with `publication_ready=false`. Model review is not human approval.

Defaults are Hybrid/C, top_k=5, candidate_k=30, RRF constant=60, and 1024 embedding-model context tokens. They are development-informed demonstration settings, not independently selected test results. The M4 packer still stops at the first block that exceeds its budget. M5 separately counts the full generation/review prompts with its own pinned tokenizer; provider parity is not established.

This version implements one-question orchestration, not persistent model serving, batch JSONL, content deduplication, a new packing policy, date filtering, network retries, measured monetary cost, independent semantic evaluation or M6 reporting. Unknown date flags are rejected; no derived date index is created. Startup repeats for each invocation and may take time. Retrieval/startup has a 600-second default deadline (configurable 30..1800 seconds); slow stages print a progress line every 30 seconds. The paid pipeline retains its existing API timeouts and does not silently retry calls.

## Validation scope

Offline tests cover the bridge states, selected-index/config binding, key isolation, interpreter failures, timeouts, query-as-data handling, output preservation and real subprocess execution of M5 preflight/contract export with mocked retrieval. SQLite distance checks are tested with a temporary database. They do not establish actual model retrieval or semantic accuracy.

The developer session can run the actual M5 interpreter and inspect local data paths. It cannot launch the user's Python 3.11 interpreter in its restricted execution context. A full live M4 run of this new entry therefore remains pending execution in the user's PowerShell. Prior notebook live checks do not by themselves verify this new entry. No paid API calls were used to build or test this package.
