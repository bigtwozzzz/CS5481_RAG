# M5 local token budgeting v0.5

This update adds an official offline tokenizer check before generation, review,
and either form of repair. It does not call the API, change prompts, or turn
automatic review into human approval. It supersedes the byte-only budgeting
description in earlier M5 documents.

## Install and check

After installing this update, use the project's Python environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-m5-tokenizer.txt
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.m5_generation.pipeline_cli --input documents/m4/m5_hybrid_C_example.json --dry-run
```

Only `tokenizers==0.22.2` and its declared dependencies are needed. No Torch,
Transformers, embedding model, or API key is required for this preflight.
The tokenizer JSON files are installed locally; runtime counting makes no
network requests. Missing dependencies, unexpected versions, or changed asset
hashes cause an explicit error before requesting an API key.

## What is counted

The complete system prompt, serialized user message, and official sample chat
markers are tokenized together. The user message includes the question, source
text, citation metadata, and any revision feedback. For review, it also includes
the draft claims and their quotes. Formatting-repair instructions are recounted
after they are appended. Each actual request records its own count and payload
hash; a preflight count is not reused for a changed repair request.

The local application policy is:

```
input tokens + output reserve + 512-token safety allowance <= 8192 tokens
```

Generation reserves its configured 1600 output tokens; review reserves 2400.
8192 is a project policy, not a claim about the model's maximum context length.
The prior 16000/24000-byte checks remain as additional size guards.

Initial generation may exclude whole lower-ranked evidence chunks until both
checks fit. It records exclusions as `input_token_limit` or `input_byte_limit`.
The highest-ranked chunk must fit in full. A repair keeps the same evidence as
its first generation; an oversized repair stops rather than deleting evidence.
Review never removes evidence to make the request fit. No stage silently clips
source text. Insufficient retrieval evidence and retrieval errors still take
their original zero-API paths.

## Official sample and limitations

Source: https://api-docs.deepseek.com/quick_start/token_usage

Archive: https://cdn.deepseek.com/api-docs/deepseek_v4_tokenizer.zip

Accessed 2026-11-20. The original tokenizer JSON and configuration are retained
under `vendor/m5/deepseek_v4_tokenizer`, with hashes and `PROVENANCE.json`.
Only data files are loaded; the downloaded Python demo is not executed, and no
remote Python code is trusted. The sample chat template is specialized to the
exact M5 request shape: one system message, one user message, generation prompt
enabled, text-only JSON output, thinking disabled, no tools. Other request shapes
and models fail closed. The reviewed model profile is `deepseek-flash`.

The official page links a V4 tokenizer sample, while the model documentation
currently maps `deepseek-flash` to `DeepSeek-V4.1-Flash-1017`. It does not prove
that the sample and deployed API use identical preprocessing or chat framing.
The sample configuration also says `model_max_length=16384`, which is not used
as the current API context limit. The pricing page currently lists 1M context.

Accordingly, a local PASS means the request fits the local policy. It does not
mean exact server parity or guaranteed billing prediction. Logs deliberately
keep `provider_tokenizer_parity_verified=false`; API usage remains authoritative.
The 512-token allowance is a chosen margin, not a proven upper bound on every
possible provider-side difference. Larger-context work should calibrate against
representative API usage and reconfirm model/tokenizer documentation.

Reconstructing the already-saved Eris generation and failed-review requests
gave local counts of 2004 and 2164, compared with historical API usage of 2028
and 2188. These two related requests each differed by 24. No new API call was
made for that comparison. This is a small diagnostic observation, not an
independent evaluation or universal correction factor. Future actual calls log
both counts and their difference when usage is available. No missing usage is
invented. The earlier failed pipeline remains ERROR.

## Verification and remaining work

Offline regression tests cover whole-chunk selection, exact budget boundaries,
multilingual text, review and repair limits, zero-call preflight failures,
unsupported models, missing dependencies, changed tokenizer data, and request
audit records. Mocked API responses do not measure answer or reviewer accuracy.
The official sample template was independently rendered in an isolated
verification environment for four supported system/user message cases and
matched the specialized renderer. Jinja2 is not a runtime project dependency.

Remaining work includes a successful real full-pipeline run, live M4 integration,
human gold evaluation, temporal-boundary cases, refusal/conflict/injection tests,
and final deliverable documentation. Local token budgeting does not complete M5.
