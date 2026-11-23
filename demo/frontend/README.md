# News RAG Demo frontend

The canonical frontend is `demo/frontend/` inside this repository. It uses the API in `scripts/demo/`; no credentials or model calls run in the browser.

## Local development

Start the backend from the repository root with `.venv_m5/bin/python -B -m scripts.demo.server` (requires the prepared M4 runtime and local gateway configuration).

From this directory:

```sh
npm ci
npm run dev
```

Open http://127.0.0.1:8080. The Vite proxy forwards `/api` to http://127.0.0.1:8765. Both servers bind only to loopback. Run `npm run build` to build `build/`, and `npm run preview` to serve that build with the same proxy. Do not run dev and preview on port 8080 at the same time.

## Guides and sample questions

- [中文：本地配置与启动](../../documents/demo/Demo_本地配置与启动_中文.md)
- [中文：功能与展示指南](../../documents/demo/Demo_前端功能与展示指南_中文.md)
- [English API and operation guide](../../documents/demo/README.md)
- [17 demo questions](../../examples/demo/batch_demo_questions.jsonl)

No local environments, node_modules, build outputs, knowledge-base databases, model caches, credentials, runtime records or archive files are part of the frontend source delivery. These questions are development/demo inputs, not independent holdout data.
