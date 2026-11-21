# M5 English generation and M4 v2 file integration (v0.3)

The active M5 CLI, model prompts, refusal messages and review reasons are in English. The four introductory demonstration scripts and M5 fixture questions are also translated. Source evidence, exact quotations, source metadata and historical run records are not translated. Historical Chinese records can still be reviewed. Earlier Chinese teaching documents are retained as historical guidance.

## Saved M4 input

From the project root, validate the supplied M4 example without an API call:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.m5_generation.cli --input documents/m4/m5_hybrid_C_example.json --dry-run
```

Expected: READY_FOR_GENERATION; retrieval_response.v2; 5 candidates; 3 selected evidence chunks; API calls 0. This reads a real retrieval record supplied by M4, not a live retrieval run on this machine. The recorded upstream latency is historical and must not be reported as local latency.

The CLI accepts a v1 response, a v2 response, or the M4 wrapper containing retrieval, context, context_tokens and selected_chunk_ids. It checks the wrapper context against the original selected text and metadata, rejects unknown/duplicate/reordered selections, and keeps only selected evidence in the generation payload. The unmodified original input is retained for traceability, but is not sent to the model. M5 assigns S1, S2, ... to the allowed evidence, then applies its temporary byte guard. Only the evidence surviving that guard may be cited or reviewed. An empty selected context is an error, not a semantic refusal.

The local v2 structural checker supports only the keywords used by the delivered schema; it is not a general JSON Schema library. Common runtime checks also verify hashes, ranks, scores and source metadata consistency. These checks do not establish source authenticity. Early v2 ERROR responses may contain an empty query, null index and only config.mode; their upstream error is retained as a system failure without an API call.

## Generate and review

Removing --dry-run permits one paid DeepSeek generation call. --repair-once allows at most two generation calls for structure, citation or output-language failures. Semantic repair is not integrated. Enter the API key only in the hidden terminal prompt.

Review a saved answer with:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.m5_generation.review_cli --input m5_runs/ACTUAL_ANSWER_FILENAME.json
```

Replace the filename with the actual new answer record. One review permits at most one additional paid API call. Generation and review remain separate steps. PASS is an automatic model judgment, not human approval; generated drafts remain publication_ready=false.

English is specified in both prompts. A local guard rejects CJK prose in newly generated claims, information gaps and review reasons; it is not a complete language classifier. Exact quotes and historical input are exempt. The guard does not guarantee that all other non-English languages are detected. Prompt versions are m5-generation-en-v0.3 and m5-support-en-v0.3.

The reviewer now explicitly distinguishes missing support from contradiction. For example, "at least 12" does not establish "at least 120", but the two are not necessarily contradictory. This prompt change has been checked offline; its real-model effectiveness has not been measured.

## Remaining work

The M4 example reports 1012 embedding-tokenizer tokens within its 1024-token proxy budget. M5 has not recomputed that count. Generation still uses a 16 KB byte guard and review a 24 KB byte guard. Neither is the generation model tokenizer budget. The final tokenizer budget must include prompts, question, serialized evidence and output allowance.

This update needs no numpy, Chroma or model cache to read saved M4 JSON. Running M4 live is a separate step requiring its documented Python 3.11 environment and dependencies. Do not install M4 dependencies into the current M5 environment just to read this example.

Live retrieval, generation-tokenizer budgeting, integrated semantic repair, explicit corpus time-boundary enforcement and systematic human answer/refusal evaluation remain unfinished. Passing unit tests does not establish answer accuracy or reviewer reliability.

## Offline checks

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -p "test_m5*.py"
```

API responses in unit tests are simulated. The tests check program behavior; they are not model-quality measurements.
