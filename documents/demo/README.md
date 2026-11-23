# Local RAG Demo

- [中文：本地配置、启动与知识库位置](Demo_本地配置与启动_中文.md)
- [中文：前端功能与展示指南](Demo_前端功能与展示指南_中文.md)
- [Frontend source and instructions](../../demo/frontend/README.md)
- [17 development/demo questions](../../examples/demo/batch_demo_questions.jsonl)

The canonical frontend is `demo/frontend/` inside this repository. The API reuses the existing M4 validation/retrieval and M5 G0/G1/G2 protocol implementations without modifying frozen experiment code.

## Start

From the CS5481_RAG root:

```sh
.venv_m5/bin/python -B -m scripts.demo.server
```

In a second terminal, from the repository root:

```sh
cd demo/frontend
npm ci
npm run dev
```

Open http://127.0.0.1:8080. Choose the prepared `.local-m4` workspace through the local directory browser. A valid workspace contains `m3_data`, `runtime_chroma`, and the exact embedding snapshot under `model_cache`. This is a loader for the project's prepared M4 knowledge bases, not a PDF ingestion service. Loading validates document/index hashes and model identity; it does not download models.

The backend uses `.venv/bin/python` for M4 and the M5 process for token budgeting and gateway calls. Override the retrieval interpreter with `--m4-python /absolute/path/to/python` if required. Both servers bind to loopback. Keep them local; this is not a public multi-user service.

School gateway configuration is read from process environment, falling back to the gitignored project `.env`. Only `M5_API_BASE`, `M5_API_KEY`, and `DEEPSEEK_API_KEY` are read. Never put credentials into frontend files. The model/profile is `configs/m5_budget_cityu_cs5351.json`. Existing local credentials are not sent to the browser or M4 process. `/api/status` reports configuration presence, not a successful authentication probe.

All tasks require an explicit UI action. G0/G1 normally make one model call per question; G2 normally makes two and can make four with repair. There are no network retries. The stop button requests cooperative cancellation: in-flight work can finish and use credit; no later question or model stage should be dispatched after cancellation is observed. No correctness scores are fabricated. Costs stay null without a verified pricing snapshot.

Task snapshots, retrieval/packing records and model-call ledgers are written under gitignored `m5_runs/demo/`. A restarted backend can export saved tasks, but interrupted work is not resumed or retried automatically.

## API

- `GET /api/status`: service, credential-presence flag, knowledge-base state and fixed configuration.
- `GET /api/directories?path=...`: directory-only browser on the same computer; no file uploads or file download endpoint.
- `POST /api/knowledge-base/load {path}`: asynchronously validate/load a workspace; poll status.
- `POST /api/knowledge-base/unload {}`: unload selection when idle.
- `POST /api/questions/validate {text}`: JSONL validation, 1–100 unique nonempty string IDs/questions, no extra fields, maximum 1 MB.
- `POST /api/tasks {knowledgeBaseId, protocol, questions}`: start a single or batch task; only one active task is accepted.
- `GET /api/tasks/:id`: actual progress and results.
- `POST /api/tasks/:id/stop {}`: request stopping; poll until terminal.
- `GET /api/tasks/:id/export?format=json|jsonl|csv`: local result download; CSV escapes formula prefixes.

Unknown token usage remains null; zero is used only where zero calls are recorded. Call latencies and per-question completion times are separate. A citation's exact quote does not establish semantic correctness. The UI has no automatic human-score or gold ingestion endpoint.

## Verification

```sh
.venv_m5/bin/python -B -m unittest tests.test_demo_api -v
```

Frontend build: `npm run build`. Tests use synthetic data and do not call the model gateway.

## Source delivery

Commit frontend source/lockfile, backend source, tests, guides and the small sample question file. Do not commit dependencies, builds, archives, environments, local credentials, databases, caches or generated run directories. The original sibling `nocode/` is retained as a historical local working copy; maintain `demo/frontend/` from now on.
