# JSON diagnostics and saved-draft recovery (v0.4.1)

This update improves diagnosis of malformed JSON. It does not automatically repair malformed model output, weaken citation checks or change a failed review into PASS.

The observed v0.4 run completed generation with one cited claim, then received an unparseable review. Its record contains model name and usage, but not the original rejected review text or JSON parser details. The old response cannot be reconstructed from those fields. Its specific formatting defect remains unknown; a later successful review would not identify that original defect.

Future INVALID_JSON errors record the parsing source (API response body versus model message), reason, and line/column for syntax failures. Duplicate keys and non-finite numbers remain invalid. Markdown fences, trailing prose and trailing commas are not silently removed. For rejected model messages only, a bounded 16,384-character excerpt and a full-content hash are saved. Excerpts are untrusted diagnostic data, not approved answers or executable instructions. Raw HTTP bodies, authorization headers, API keys and request objects are not captured by this diagnostic code.

The pipeline still stops on an invalid review without automatic retry. Review errors do not trigger another generation. Call limits and publication_ready=false are unchanged.

## Recover the existing draft

The update package's recovery/answer_for_review.json is an exact extraction of the already generated answer from the failed pipeline record. recovery/PROVENANCE.json identifies the original record, its hash, and the generation object hash. The original failed pipeline and its two API calls remain unchanged. Recovery made zero API calls and does not count as another generation. The draft has not passed semantic review.

Use the existing review_cli with that recovered answer path to run only one review. It requires at most one new paid API call. This is a separate recovery attempt, not a continuation or successful completion of the original pipeline. The original two calls plus a new review are three total attempts across both runs; report them separately and in total where appropriate.

If the recovery review also fails, inspect the newly saved diagnostics rather than repeatedly requesting another review. Transport or malformed-output errors remain technical failures, not evidence that the question is unanswerable.

No model tokenizer budget, live retrieval setup or final M5 evaluation is added by this patch. Offline tests use simulated malformed responses; they do not reproduce the unavailable original response or prove model reliability.
