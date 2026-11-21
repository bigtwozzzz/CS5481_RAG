# B orchestration v0.9

The new `scripts.m5_generation.b_cli` coordinates A retrieval and the existing M5 generation, C hard validation, model review and one shared content repair. Default mode performs local checks; `--generate` explicitly enables paid calls. English runtime and prompts remain in use. This is implementation/functional validation, not M6 quality evaluation.

## Entry points

Use the M5 Python environment. `--retrieval-run` consumes an existing completed A batch after validating its manifest, row count, artifact hashes and evidence/audit bindings. It does not repeat retrieval. `--question` or `--input-jsonl` runs A once in the M4 Python environment, then processes its results sequentially in M5. These live modes require `--work-base`. The subprocess receives no DEEPSEEK_API_KEY or OPENAI_API_KEY. Normalized references and gold labels are not supported question fields; A rejects them.

The default live retrieval settings are Hybrid/C, k=5, candidate_k=30, RRF=60, 1024 embedding tokens and explicit `skip_continue_dedup_v1`. The legacy A default is unchanged. CLI overrides are saved in the live run. Existing A output retains its own recorded configuration.

Batch size defaults to at most 10 rows. Increase `--max-items` deliberately, up to 1000. All A file bindings are validated before generation starts. Output directories must be new; there is no automatic resume. Malformed individual questions become A ERROR rows; structurally corrupt batch manifests abort before paid work.

## Credentials and model profile

The production API reader uses only `DEEPSEEK_API_KEY` from the process environment. It never prompts, saves or prints the value. All existing generation/review CLIs using this reader inherit the change. Historical standalone practice scripts are outside the production interface and are preserved.

Only the existing reviewed `deepseek-flash`, non-thinking, text/JSON profile is supported by the local budget module. Temperature is used for that profile; unsupported models fail before API dispatch. This update does not silently change model, endpoint or tokenizer assets.

## Retry and repair limits

The B entry defaults to one transport retry per logical request. Retryable codes: HTTP_429, HTTP_502, HTTP_503, HTTP_504, NETWORK_ERROR and API_TIMEOUT. One second of bounded backoff precedes the retry. Authentication, balance, invalid input, redirect, JSON/schema and semantic failures are never transport-retried. `--network-retries 0` disables transport retries.

There are at most four logical calls per item (generation, review, repair generation, repair review) and one shared content repair. With retries enabled the hard bound is eight physical requests per item; otherwise four. Every physical dispatch is checkpointed before sending and records stage, logical call, network attempt, duration, usage and outcome. Network retry does not consume or reset the shared content repair. Existing pipeline_cli and direct run_pipeline default to zero transport retries for compatibility.

The existing transport uses a 45-second socket timeout and bounded response size. A timeout can occur after the provider has processed a request; retries may incur additional cost. Such requests remain unknown in the cost total. Cancellation is recorded and later batch rows are marked BATCH_ABORTED. Other item errors do not disappear from the JSONL denominator. A credential/balance error also stops further paid work.

## Final text and states

The application derives ANSWERED/PARTIAL/INSUFFICIENT_SOURCES from validated claims and gaps and requires agreement with the accepted draft. C's support and scope gate is still required for generated answers. Failure after the shared repair remains ERROR/BLOCKED; a technical ERROR is not knowledge refusal. Claims are never added by the renderer. Source titles/dates/URLs come from evidence metadata and are rendered separately. All outputs, including the old generate_answer no-evidence branch, now remain publication_ready=false.

Generation, repair and judge prompts are retained as versioned files and hashed in the batch manifest. The repair prompt is appended only to repair requests and included in budget checking. Every repair uses the original evidence; failure to fit repair input produces an explicit error rather than truncating evidence.

## Usage and costs

`pipeline.api_calls` is the authoritative physical-request ledger. Generation/judge child call counts describe logical invocations; do not add them to the pipeline total. Batch `api_requests` counts physical requests once, including retries.

`--pricing-json` accepts a rate snapshot matching configs/m5_pricing.template.json. Fill verified rates per million tokens, currency (USD/CNY), model, pricing source and UTC verification time. Null template rates are intentionally rejected. No current provider rates are invented or bundled. You may run without prices, but paid cost is UNKNOWN until a valid snapshot is supplied.

Costs use provider-reported prompt/completion and cache-hit/cache-miss tokens with Decimal arithmetic. Different cache rates require a valid cache breakdown. A different returned model is not silently mapped to the configured price. Missing usage, failed requests or unknown outcomes make total_cost null; known_response_cost is only a subtotal. No-request runs cost zero. Estimates are not account invoices. Dollar values are not substituted for CNY.

## Records and handoff

Saved-run mode writes run.json, predictions.jsonl and item_XXXX directories. Live mode adds questions.jsonl, retrieval_config.json, retrieval/ and generation/. Every generation item contains the exact supplied retrieval, pipeline checkpoints and C public-contract artifacts. A contract export failure suppresses the answer row while preserving the original diagnostic pipeline and physical call ledger. Interrupted batches retain partial files and never claim COMPLETE.

The run manifest records input provenance, retrieval configuration, code/prompt hashes, elapsed time, status counts, pricing snapshot and billing completeness. JSONL rows include final text, structured claims/sources, scope gaps, errors, contract status and a hash/path to the complete pipeline. API-returned tokens are in that pipeline ledger; no secret/environment dump is logged.

Offline tests use mocked model responses and synthetic price examples. They establish control flow, accounting and hard-contract behavior, not real semantic accuracy. After installation, first validate existing A evidence without API calls, then perform a small explicitly enabled real API acceptance and verify current provider prices. New live B single/batch routing also requires a user-machine smoke check. M6 development/holdout evaluation remains D's work.
