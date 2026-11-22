# M5 A B C handoff

## macOS local acceptance

The local M4 interpreter is `.venv/bin/python` (Python 3.11); M5 uses
`.venv_m5/bin/python` (Python 3.13, tokenizers 0.22.2). Keep these environments
separate. The existing data, runtime database and model cache are in `.local-m4`.
B now accepts `--m4-python` and selects native Windows/macOS executable paths.

Run from the repository root; every output directory must be new:

```bash
.venv_m5/bin/python -B -X utf8 -m unittest discover -s tests -p 'test_m5*.py'
.venv/bin/python -B -X utf8 -m scripts.m4_retrieval.cli --input-jsonl examples/m5/a_smoke_questions.jsonl --packing-policy skip_continue_dedup_v1 --check-only
.venv_m5/bin/python -B -X utf8 -m scripts.m5_generation.b_cli --input-jsonl examples/m5/a_smoke_questions.jsonl --work-base .local-m4 --m4-python .venv/bin/python --packing-policy skip_continue_dedup_v1 --top-k 5 --network-retries 0 --max-items 2 --dry-run
```

Local acceptance produced `m5_runs/macos_dry_run_01/retrieval` and
`m5_runs/macos_dry_run_01/generation`: both questions passed retrieval,
generation-budget and contract checks; zero API requests were made.
The offline suite passed 263 tests, including two new native-interpreter checks.

To generate using those exact saved retrieval results, set `DEEPSEEK_API_KEY`
in the terminal environment and run the following paid command:

```bash
.venv_m5/bin/python -B -X utf8 -m scripts.m5_generation.b_cli --retrieval-run m5_runs/macos_dry_run_01/retrieval --max-items 2 --network-retries 0 --generate
```

This permits at most eight physical requests for the two questions, including
review and bounded repair. Without verified `--pricing-json`, token usage is
recorded and monetary cost remains unknown. A dry-run is not a generated answer;
automatic checks are not human approval. Real generation requires a valid key.

For an OpenAI-compatible school gateway, configure `M5_API_BASE` and `M5_API_KEY`
in the ignored local `.env` instead of using `DEEPSEEK_API_KEY`. The base must be
HTTPS; gateway keys are never used with the default provider. Load the local
file explicitly when running B, for example:

```bash
.venv/bin/python -m dotenv run -- .venv_m5/bin/python -B -X utf8 -m scripts.m5_generation.b_cli --retrieval-run m5_runs/macos_dry_run_01/retrieval --max-items 2 --network-retries 0 --generate
```

The supplied school gateway hostname currently fails DNS resolution on this
machine, so its available models and real generation have not been verified.
The existing reviewed tokenizer profile still requires `deepseek-flash`; another
model requires an explicit budget/profile adaptation before generation.

The M5 engineering delivery adds retrieval adaptation, evidence packing, generation, bounded repair, public contracts and automatic support/relevance review. Start with [the consolidated Chinese handoff for D](documents/m5/M5_ABC_HANDOFF_FOR_D_中文.md).

Use `scripts.m5_generation.b_cli` for current single/batch integration. A live dry-run executes local retrieval but makes no DeepSeek calls; `--generate` enables paid calls. Environment setup and input/output fields are documented in the handoff. M4 setup remains in README_FIRST.md and M4_HANDOFF.ipynb.

Validation: 261 offline checks passed on the delivered Windows environment; selected historical real runs and the current C relevance regression are classified under documents/m5/handoff_evidence/INDEX.json. Independent development/holdout evaluation, human scoring, G0/G1/G2 comparison and M6 reporting are not complete. Automatic model review is not human approval; publication_ready remains false.

The package excludes virtual environments, databases, model caches and full run history. Pinned offline tokenizer JSON assets retain their provenance. Older module documentation and saved absolute paths describe historical versions; consult the consolidated handoff for current behavior.
