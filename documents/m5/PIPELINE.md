# M5 bounded generation and review pipeline (v0.4)

The new command chains English generation, local citation checks, model review and at most one shared repair. This is still a development pipeline using saved M4 input; it is not a claim that all M5 requirements are complete.

## Start without an API call

From the project root:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.m5_generation.pipeline_cli --input documents/m4/m5_hybrid_C_example.json --dry-run
```

Expected: Status READY_FOR_PIPELINE; Gate NOT_RUN; Evidence items 3; API calls 0. No key or additional dependency is needed.

## Run generation and review

Remove --dry-run to use the official DeepSeek API. The key is requested once, retained only in process memory during the run and never written to output. A normal successful run uses two calls. A semantic failure may use four: generation, review, one replacement generation, one final review. A format/citation failure uses the same single repair allowance; it cannot obtain a second semantic repair. --no-repair limits the process to at most two calls. These are upper limits, not guarantees of token usage or price. A timeout may still consume account credit.

Generation, review and repair use the same model unless --model selects another. This does not provide independent model adjudication. Network errors and malformed review outputs stop the run without automatic retry. A failed final review produces status ERROR, gate BLOCKED and code REVIEW_REJECTED, with no answer in the top-level output. It does not pretend the question has no answer. NO_EVIDENCE from M4 produces a fixed INSUFFICIENT_SOURCES response with zero API calls; an M4 ERROR remains a system failure.

## Output files

Each invocation creates a new m5_runs/pipeline_<id> directory. pipeline.json records the preflight, each generation and review, original evidence, repair feedback, call budget, observed usage and errors. Checkpoints are written during processing; interrupted requests can have an unknown outcome or unknown usage. A received response does not itself mean the draft passed validation. Existing output directories are never overwritten.

On automatic success, the terminal displays a draft and saves answer.json. The overall gate is AUTOMATIC_REVIEW_PASSED, but publication_ready remains false and human_review remains not_performed. The nested generation record retains its generation-only validation fields; consult its associated review in pipeline.json for the semantic decision. Rejected drafts remain only in diagnostic attempt records and are not exported as answer.json. Do not use diagnostic attempt text as an approved answer.

The saved automatic PASS for the earlier Eris answer and the user's C2 relevance annotation are not modified or retroactively reclassified. The revised prompts apply a general deletion test: remove a claim when all requested information remains answered without losing an essential qualification. This improvement was informed by an observed development example, not by an independent test set. Model judgments may still be wrong.

## Evidence and repair constraints

M4 packing selection is respected. Evidence identifiers and text must remain identical across generation attempts. Previous answers and review reasons enter the replacement request as untrusted user data, never system instructions or new evidence. The generator must check feedback against the original evidence. If the extra feedback exceeds the temporary byte limit, the run stops before another API call rather than dropping evidence to make room.

## Remaining limitations

- Generation-model tokenizer budgeting is still NOT IMPLEMENTED. The 16 KB generation and 24 KB review guards are temporary byte limits. Adding repair feedback increases input size.
- Local live M4 retrieval, explicit corpus time-boundary enforcement, systematic human annotation and answer/refusal evaluation remain unfinished.
- Automatic PASS does not establish truth, source authenticity, complete coverage or human approval. Model review can miss unnecessary or unsupported claims.
- Costs remain null without a verified pricing calculation; observed token usage is recorded when the API supplies it.
- This update has offline tests with simulated API responses. Those tests establish state transitions and limits, not reviewer accuracy or actual model improvement.

Run the M5 offline checks with:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -p "test_m5*.py"
```
