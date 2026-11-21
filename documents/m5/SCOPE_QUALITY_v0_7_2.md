# M5 scope quality update v0.7.2

The live passport-number refusal included unrelated missing-person counts in its gap explanation. The generator and reviewer now explicitly apply support and relevance rules to every clause of missing_information, including refusals with no claims. This is prompt hardening, not a deterministic semantic guarantee.

No schema or CLI changes. The existing missing_information_accurate flag still controls the scope gate. A failed scope check uses the existing one shared repair, with unchanged evidence and at most four total API calls. A second failure blocks answer display. Both prompt versions are recorded as v0.7.2. Historical runs are not reclassified or edited.

The action-question guidance also preserves planned versus completed actions and excludes actions unrelated to the requested purpose. A supported statement can still be unnecessary.

Offline tests mock the judge to check control flow. They do not establish that the live model detects every violation. A fresh live refusal and review are still required to assess prompt behavior; do not rerun until a pass occurs. publication_ready remains false and no human approval is recorded.

Suggested gap: "The supplied reports do not provide the missing travellers' passport numbers."

Acceptance: run the offline test suite, then use the existing saved live retrieval as pipeline input for a fresh run. Keep the prior answer and review as historical evidence. Confirm the new gap does not contain unrelated counts, the prompt versions are v0.7.2, and any repair remains within the shared limit. Actual provider token usage remains authoritative.
