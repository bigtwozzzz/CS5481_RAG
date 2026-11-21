# M5 public contracts v0.6

This additive delivery exports and validates saved M5 v0.5 pipeline records. It does not call an API, rerun retrieval, change prompts, or modify the original records. It does not yet insert these JSON Schemas into the live generation entry point. Integration with a unified live/batch entry point remains future work.

## Quick start

Run from the project root in PowerShell, using the existing M4 Python environment:

```powershell
.\.venv_m4\Scripts\python.exe -B -X utf8 -m scripts.m5_generation.contracts_cli --pipeline m5_runs/pipeline_6d6c5e00bc2746a08fd8b51aaec555ff/pipeline.json
```

The command creates a new `m5_runs/contracts_<id>` directory. A successful one-attempt pipeline exports seven artifacts plus `summary.json`: four attempt artifacts and three final artifacts. An existing output directory is refused. Validation finishes before output creation; an interrupted disk write can leave an incomplete new directory without a summary. Preserve it and use a new output path.

The extra validator dependency is `jsonschema`; the existing M4 environment already contains it. `requirements-m5-contracts.txt` pins the tested optional dependency for a separate environment. Exporting records does not load the embedding model or tokenizer. Do not install or downgrade packages in an established environment just to run this command.

## Four contracts

| Schema | Meaning | Important rules |
|---|---|---|
| `evidence_bundle.v1.schema.json` | Complete selected chunks and their citation metadata | READY, NO_EVIDENCE or ERROR; sequential S labels; hashes and selection checked in Python |
| `generation_draft.v1.schema.json` | Existing model response: status, claims, missing_information | ANSWERED requires claims and no gaps; PARTIAL requires claims and gaps; INSUFFICIENT_SOURCES has no claims and explains gaps |
| `validation_report.v1.schema.json` | A separately bound automatic review, or an explicit unreviewed state | PASS, FAIL, ERROR, NOT_RUN or NOT_APPLICABLE; never human approval |
| `answer_response.v1.schema.json` | Existing saved answer, including system errors | Three answer states plus ERROR; ERROR exposes no answer, claims or sources |

All four are standalone JSON Schema Draft 2020-12 files with internal definitions only. Use a format checker for date-time and URI validation. Schema compliance alone cannot enforce cross-field equality, evidence membership, semantic support or authenticity; use the Python adapter as well.

The model draft deliberately retains its existing three-field wire format: the caller selects schema v1, without injecting a new `schema_version` field into the model response. Existing prompts and runtime formats remain compatible. Four-state consumer handling belongs to the answer/pipeline layer; the model is not asked to generate technical ERROR states.

## Public Python interfaces

```python
from scripts.m5_generation.public_contracts import (
    validate_schema, validate_answer, evidence_bundle_from_record,
    validation_report_from_review, export_pipeline_contracts,
)

# Hard checks only. Returns support="unchecked" when claims exist.
local_result = validate_answer(saved_answer, evidence_bundle=trusted_bundle)

# Bind an existing automatic review; makes no new model call.
report = validation_report_from_review(saved_answer, saved_review)

# Without saved_review the decision is NOT_RUN, never PASS.
unreviewed = validation_report_from_review(saved_answer)
```

Existing `generator.generate_answer`, `support.review_answer` and `pipeline.run_pipeline` remain the generation, semantic-check and orchestration interfaces. There is no new paid `check_support` alias in this release. `validation_report_from_review` validates stored verdict consistency; it does not reassess whether a judge's explanation is correct. Automatic judgments can be wrong.

Quote offsets are zero-based Unicode character indices within the exact selected chunk text, with an exclusive end, matching Python string slices. They are not UTF-8 byte positions or article-wide offsets. Original source quotes are preserved; generated prose and runtime messages are English.

Hashes use UTF-8 JSON with sorted keys, compact separators, unescaped Unicode and finite values. File hashes in the export summary hash actual file bytes. These two hashes serve different purposes. Neither is a digital signature or proof of source authenticity. When saved M4 provenance is present, the adapter revalidates it and checks selected evidence membership/order and metadata. Without that provenance it checks only the supplied evidence's internal consistency; use an independently trusted bundle for stronger binding.

The evidence bundle explicitly describes selection, not proof that the exact content reached the provider. Token totals are checked for arithmetic consistency, not recomputed by this export command. Provider/local tokenizer equality remains unverified; API usage is authoritative.

An exported PASS preserves a completed `llm_judge` review bound to the exact answer hash and snapshot, and recomputes its decision from individual stored verdicts. It is not an independent second assessment. `publication_ready=false` remains in exported pipeline answers and reports. Historical standalone deterministic no-evidence refusals may use `publication_ready=true`; that legacy exception does not authorize publication of model claims. Old Chinese historical records are preserved, but are not promised to satisfy this current English delivery.

## Examples and checks

`examples/m5_contracts/` contains four explicitly synthetic, offline-mocked pipeline examples, their exported contract views, and an `INDEX.json`. They demonstrate ANSWERED, PARTIAL, INSUFFICIENT_SOURCES and ERROR handling; they are not live evaluation records or evidence of model quality. They are kept outside `examples/m5/` because that directory holds retrieval fixtures.

```powershell
.\.venv_m4\Scripts\python.exe -B -X utf8 -m scripts.m5_generation.contracts_cli --pipeline examples/m5_contracts/answered/pipeline.json
```

The new `tests/test_m5_public_contracts.py` checks review/answer binding, modified citations and offsets, changed selected metadata, invalid states, refusal/error handling, uncertainty, repair history and no-overwrite behavior. Full regression execution uses the existing M5 tokenizer dependencies plus the optional schema dependency. Mocked reviews exercise control flow, not semantic accuracy.

Remaining acceptance work includes a unified live question/batch interface, event-separated evaluation data, human semantic checks, actual repair/cost measurements, configuration freezing, and final M5/M6 handoff. This delivery does not complete those tasks.
