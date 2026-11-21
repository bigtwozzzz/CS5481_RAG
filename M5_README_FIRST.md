# M5 A B C handoff

The M5 engineering delivery adds retrieval adaptation, evidence packing, generation, bounded repair, public contracts and automatic support/relevance review. Start with [the consolidated Chinese handoff for D](documents/m5/M5_ABC_HANDOFF_FOR_D_中文.md).

Use `scripts.m5_generation.b_cli` for current single/batch integration. A live dry-run executes local retrieval but makes no DeepSeek calls; `--generate` enables paid calls. Environment setup and input/output fields are documented in the handoff. M4 setup remains in README_FIRST.md and M4_HANDOFF.ipynb.

Validation: 261 offline checks passed on the delivered Windows environment; selected historical real runs and the current C relevance regression are classified under documents/m5/handoff_evidence/INDEX.json. Independent development/holdout evaluation, human scoring, G0/G1/G2 comparison and M6 reporting are not complete. Automatic model review is not human approval; publication_ready remains false.

The package excludes virtual environments, databases, model caches and full run history. Pinned offline tokenizer JSON assets retain their provenance. Older module documentation and saved absolute paths describe historical versions; consult the consolidated handoff for current behavior.
