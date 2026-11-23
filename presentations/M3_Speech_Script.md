# M3 Speech Script

Scope: slides 11 to 14  
Estimated speaking time: about 2 minutes

## Slide 11 — M3 transition

M2 gave us three versions of the same news corpus. In M3, we turn each passage into a vector so the retriever can search by meaning. We keep the passage and its source alongside the vector so a later answer can cite the evidence.

## Slide 12 — Embedding and indexing pipeline

We check the chunk schema and IDs first. Then we encode the text locally with the pretrained all-MiniLM-L6-v2 model, in batches of 64. Each vector has 384 dimensions and is normalized to unit length. A SQLite cache reuses a vector when the exact text and model version match. We write the records to persistent Chroma collections using cosine distance, with one collection per chunking strategy.

## Slide 13 — Index build and checks

The three collections contain 49,361 chunk records in total. We used the same model snapshot for all three, so the encoding stayed fixed across strategies. We reopened each saved collection and checked its count against the manifest. Sampled records had 384-dimensional vectors and source URLs, and a test query returned passages with their citation fields.

## Slide 14 — Handoff to M4

The manifest identifies the collection and the model revision. M4 uses that same revision to encode the question, then searches the saved vectors. Each match carries a chunk ID, the original passage, and its source URL and title. The encoder has a 256-token limit, so it can truncate long chunks even though we store the full passage. I’ll now hand over to M4 to explain how we retrieve and rank the evidence.
