# Human answer scoring guide v1

This guide scores the model's final answer only. It does not change the gold standard or overwrite automatic-review verdicts. The gold standard is v1.1 in `data/evaluation/m5_dev.json` and `m5_holdout.json`. The blank score sheet is `data/evaluation/answer_score_sheet.csv`. Calibration records for existing cases are in `data/evaluation/scoring_calibration_v1.csv`. Those records fix the labelling rules and stay out of the official numerator and denominator.

Automatic PASS, FAIL, `relevant`, and `publication_ready` are not human labels. Keep the score sheet in its own file. Copy the system status unchanged into `system_status`.

## Which answer to score

Score only the final answer of that run: `answer`, `claims`, `sources`, and `missing_information` in `predictions.jsonl`. Check the file against `pipeline_file` and `pipeline_sha256` before reading it. A draft rejected before repair is not the final answer. Record `repair_used` in the notes.

When a technical failure leaves no gradeable answer, the primary label is ERROR. An empty answer is not a refusal. `EMPTY_SELECTED_CONTEXT`, retrieval failure, API failure, parse failure, contract failure, and a failed final review process are system failures.

## Fact marks

Mark every `required_facts` item on an answerable question. Each item has weight 1. The reference answer is one acceptable wording. Exact string equality is not required. Numbers, units, objects, times, and qualifiers must keep their original meaning.

| Mark | Meaning |
| --- | --- |
| PRESENT | The final answer states the fact with the right object, number, unit, and qualifier |
| OMITTED | The answer does not state the fact and does not state the opposite |
| CONTRADICTED | The answer reverses the fact, or assigns the number, object, unit, time, or qualifier to the wrong thing |

Keep approximations approximate. "about 500" may be written as about, approximately, or roughly. It may not be written as exactly 500. "Slated for 2028" may not be rewritten as "already launched in 2028". "About 46 metres" must still refer to the wreck named in the question.

Unanswerable questions have empty `required_facts` and receive no PRESENT mark. Judge only whether the answer invents the missing field and whether it explicitly says the material does not contain that information.

Write `fact_marks` as `fact_id=PRESENT;fact_id=OMITTED`. The marks must cover every required fact for the question, once each.

## Fully correct, partially correct, and factual error

These three content labels apply only to answerable questions that did not fail technically.

**CORRECT (fully correct)**

- Every required fact is PRESENT, and none is CONTRADICTED.
- G1 and G2 also require `citation_support=FULL`: every present required fact has at least one valid citation.
- G0 does not require citations. A correct fact with no citation still counts in the coverage numerator. Set the citation column to `NOT_APPLICABLE`.
- Extra correct background goes into `irrelevant_fact_count`. It does not turn a fully correct answer into a partial one.

**PARTIAL (partially correct)**

- No required fact is CONTRADICTED.
- At least one required fact is present and at least one is omitted, or every required fact is present but G1/G2 citation support is incomplete.
- When a question contains both an answerable part and a part that the material genuinely lacks, answering every answerable fact and explicitly marking the missing part is PARTIAL. That response is neither fully correct nor a refusal of the whole question.
- Set `partial_reason` to `OMISSION`, `CITATION`, `UNANSWERABLE_SLOT`, or `BOTH`.

**FACTUAL_ERROR**

- Any required fact is CONTRADICTED, or an unanswerable question is given a specific value for the missing field.
- One factual error decides the question label. The remaining facts still count as present or omitted so coverage can be reported separately.
- A wrong number in the answer remains a factual error when the cited source text is right. Writing 350 is not excused because the citation still says 35.

A factual error takes priority over partial correctness and refusal. A system failure takes priority over a factual error, because there is then no final answer to attribute.

## One citation and combined evidence

Citation support uses only text the model actually cites and that can be located in the evidence bundle for that run. Gold quotes are used to check meaning. Missing the designated gold sentence does not by itself mean the answer has no support. A synonymous passage accepted by the reviewer is allowed.

One citation may support several facts. For `m5_dev_002`, the location quote supports the training centre, Cologne, and Germany together. The year needs the other quote.

When a fact lists several `evidence_ids`, any one cited passage that is semantically sufficient supports that fact. Several claims may be combined: every claim used in the combination must be SUPPORTED, and the combined meaning must cover the fact. An unsupported claim cannot fill a gap left by another claim.

`citation_support`:

| Value | Condition |
| --- | --- |
| FULL | Every PRESENT required fact has a valid citation |
| PARTIAL | At least one PRESENT fact is cited and at least one is not |
| NONE | Required facts are present, but none has a valid citation |
| NOT_APPLICABLE | G0, or the question has no PRESENT fact that could be cited |

`citation_support` is one label for the question. The fact-level record is `fact_citation_marks`, written as `fact_id=CITED;fact_id=UNCITED`. For G1 and G2 it lists every PRESENT fact once. `FULL` means every one of those facts is `CITED`. `PARTIAL` means both values occur. `NONE` means every PRESENT fact is `UNCITED`. Citation coverage uses those marks: CITED PRESENT facts / all PRESENT facts. For G0, or when no fact is PRESENT, leave `fact_citation_marks` empty and keep `citation_support` as `NOT_APPLICABLE`.

The G0 fact-coverage denominator is still every required fact. A fact that is not stated is an omission. A fact that is stated correctly without a citation is PRESENT.

## Coverage, omissions, and irrelevant facts

Compute coverage only on answerable, non-ERROR questions. Unanswerable questions stay out of the fact-coverage denominator.

- Required-fact coverage = PRESENT count / required-fact count. Report both the micro average (counts pooled) and the macro average (mean across questions), with numerator and denominator.
- Omission = OMITTED count / required-fact count.
- Factual-error count = CONTRADICTED count. Do not subtract it from the coverage numerator. The question label is already FACTUAL_ERROR.
- An irrelevant fact is correct, supported by the source, and not required by the question. Count it. Do not subtract it from coverage. An extra claim that is false is a factual error, not an irrelevant fact.

## Correct refusal, false refusal, PARTIAL, and ERROR

| Primary label | Rule |
| --- | --- |
| CORRECT_REFUSAL | The gold item is unanswerable; the answer explicitly says the requested information is not in the material; the missing field is not invented |
| FALSE_REFUSAL | The gold item is answerable; the answer says the whole question cannot be answered and states none of the required facts |
| INCOMPLETE_REFUSAL | The gold item is unanswerable; the missing field is not invented, but the answer does not explicitly say the material lacks it |
| PARTIAL | See the section above. Re-judge a system status of PARTIAL from the facts; do not copy the status |
| ERROR | System failure. The answer cannot be scored. Keep it in the all-request denominator, and also report a denominator that excludes ERROR |

A retrieval miss or a budget that cannot fit evidence does not turn an answerable question into an unanswerable one, and that empty result is not a correct refusal. A fixed refusal after no candidates is FALSE_REFUSAL when the question is answerable. It is CORRECT_REFUSAL only when the question is unanswerable, the refusal is explicit, and nothing is invented.

When an answerable question states no required fact, does not explicitly refuse, and has no technical failure, the primary label is NO_HIT. That is neither partial correctness nor a false refusal.

The decision order is fixed: ERROR, then FACTUAL_ERROR, then the two unanswerable refusal labels, then FALSE_REFUSAL, then CORRECT, then PARTIAL, then NO_HIT. The filled `primary_label` must match the label produced by this order. `scripts/m6_evaluation/check_answer_scores.py` checks it.

## Who reviews a disputed item

The first scorer sets `disputed=YES` and leaves the final label empty. Disputes include whether synonymous evidence is acceptable, whether an approximation or qualifier has crossed the line, whether several pieces of evidence may be combined, and whether the gold standard itself is ambiguous.

The reviewer must be a different team member who did not give the first score for that item, and must fill `adjudicator` and `adjudication`. A scorer does not adjudicate their own item. If only one scorer is available, the item stays disputed and is excluded from the adjudicated score.

When the dispute is about the gold standard rather than the answer, stop scoring that item and record it in `human_review.csv` with decision `DISPUTED`. Do not edit the gold standard in the score sheet. A gold change needs a new dataset version under the annotation guide. In the current v1.1 gold, `m5_dev_002` uses the four facts training centre, 2024, Cologne, and Germany. `m5_holdout_003` uses the full names and the role mapping.

## What to fill after new answers exist

1. Copy the score sheet for each run and fill one `run_id` and one `protocol` (G0, G1, or G2).
2. Join by `id`, check the pipeline hash, and then read the final answer.
3. Fill `system_status`, `system_failure`, `explicit_refusal`, `invented_missing_slot`, `fact_marks`, `citation_support`, `fact_citation_marks`, `irrelevant_fact_count`, and notes.
4. Fill `primary_label` by the decision order. PARTIAL also needs `partial_reason`.
5. Run the check script. Send disputed items to another team member.
6. Fill the holdout only after the configuration is frozen. If the configuration changes after the holdout has been seen, report that exposure.

The dev set can be filled as soon as its answers exist. Rows with `eligible=fill_after_generation` are dev. Rows with `eligible=fill_after_freeze` are holdout.

Every reported rate includes its numerator and denominator. ERROR stays in the all-request denominator, and a second rate excludes ERROR. The 10 calibration rows are not added to these denominators.

## Boundaries fixed by existing cases

These cases fix the boundaries. The first six come from existing outputs or a constructed regression. The last four are worked examples against the v1.1 gold, not scores for a model run.

| Case | Material | Primary label | Rule applied |
| --- | --- | --- | --- |
| Eris, including the Kuiper Belt sentence | `documents/m5/handoff_evidence/c_reviews/answer.json` | CORRECT | The requested fact is the discovery of the body later called Eris, supported by one S1 quote. The location sentence is in the source but was not asked, so `irrelevant_fact_count=1`. An automatic FAIL does not change this human label |
| Eris, repaired to the discovery only | `a-smoke-eris` in `m5_runs/b_2db23a0069f644b0b69afa5728db6ce3` | CORRECT | The same fact, with zero irrelevant facts |
| Passport numbers only | `a-smoke-passports` in the same run | CORRECT_REFUSAL | System status `INSUFFICIENT_SOURCES`. The answer says the reports do not provide passport numbers and does not invent any |
| Search actions and passport numbers | `historical_states/partial.pipeline.json` | PARTIAL | The actions are supported. The passport numbers are explicitly absent. `partial_reason=UNANSWERABLE_SLOT` |
| 35 changed to 350 | `c_reviews/historical_wrong_number_review.json` | FACTUAL_ERROR | Synthetic regression. The citation still says at least 35 while the claim says at least 350. One contradicting citation decides the question |
| Retrieval failure | `historical_states/error.pipeline.json` | ERROR | Status ERROR, code `RETRIEVAL_ERROR`, empty answer. The question asks which body prompted the vote, so this is not a refusal |
| 002 answers only ESA and 2024 | Worked example | PARTIAL | Of the four facts, only the year is present. The centre, Cologne, and Germany are omitted. `partial_reason=OMISSION` |
| 002 uses the year quote and the location quote | Worked example | CORRECT | One quote supports the year. The other supports the centre, Cologne, and Germany together |
| 003 states that no day or launch time is confirmed | Worked example | CORRECT_REFUSAL | Unanswerable. The proposed year may be mentioned. It may not be turned into a confirmed launch schedule |
| 003 states a confirmed launch date | Worked example | FACTUAL_ERROR | The material has no such date. Filling the missing field is not a refusal |
