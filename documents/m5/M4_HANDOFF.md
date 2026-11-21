# M4 to M5 integration status

M5 v0.3 accepts retrieval_response.v1, the delivered retrieval_response.v2, and the saved M4 wrapper with retrieval, selected_chunk_ids, context and context_tokens.

For the recommended Hybrid/C example, use documents/m4/m5_hybrid_C_example.json with the M5 CLI. Its 5 candidates are restricted to the 3 chunks selected by M4. Exact source text and metadata are preserved. M5 may exclude further chunks under its temporary byte limit and records the reason. Only final model-input evidence is eligible for citation.

OK means candidates were retrieved, not that the question is answerable. NO_EVIDENCE causes a fixed refusal without generation. ERROR remains a system error with the original upstream error retained. Early v2 errors do not require invented query/index/config values.

The current integration is file-based. It does not rerun retrieval or validate the local Chroma/model environment. Model generation and support review remain separate commands. Generated claims, information gaps, CLI messages and review reasons use English. Quotes and original records retain their original content.

The 1024-token M4 budget uses the embedding tokenizer. M5 has not implemented generation-tokenizer budgeting; the current 16 KB generation and 24 KB review limits are byte guards only. Semantic repair, systematic human answer/refusal evaluation and explicit corpus time-boundary handling remain unfinished.

Read README.md in this directory for commands and limitations. No M4 source code or saved M4 experiment outputs are changed by this update.
