# M1 Speech Script

Scope: slides 3 to 6, excluding the total cover and group division page

## Slide 3: M1 transition

Now I’ll cover M1, the data layer behind our RAG system. The goal was to build a corpus that is large enough for retrieval, controlled enough for experiments, and traceable enough for citations.

## Slide 4: Corpus overview

We have 3,152 English articles from The Guardian’s official API. Together, they contain 2.53 million words across world, business, politics, technology, and science. We kept the complete article body rather than summaries. We also stored the canonical URL, title, byline, section, and publication time, so every retrieved passage can be traced back to its source.

## Slide 5: Collection pipeline

The collection pipeline has four stages. First, we query the API with a selected publication window. Then we extract and normalize the article text, while checking language and length. Next, we remove duplicates by article ID, URL, and normalized body hash. Finally, we freeze the cleaned output and record its checksums. The SQLite state allows us to resume collection and update the corpus without duplicating existing articles.

## Slide 6: Outputs

Our main handoff is documents.jsonl. Each line contains one complete article and all fields needed for a verifiable citation. The raw file supports auditing, while the manifest records counts, date range, and SHA-256 hashes. With this structure, the next stage can begin chunking and retrieval from a clean and reproducible source.
