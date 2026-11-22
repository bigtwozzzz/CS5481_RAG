# M2 Speech Script

Scope: slides 7 to 10  
Estimated speaking time: about 3 minutes

## Slide 7: M2 transition

Now I’ll cover M2, the chunking step in our RAG system. M1 gives us complete news articles. A question may only need a few sentences from one of them. For example, if the question asks what a study found, we want to retrieve the passage that describes the finding. Splitting articles gives the retriever smaller units to search. We keep the link to the original article so the passage can still be cited later.

## Slide 8: Chunking strategies

We tried three ways to split the same articles, with a default budget of 1,200 characters per chunk. Strategy A uses character windows with an overlap set to 150 characters. If a cut falls between a study’s name and its findings, that overlap can carry some of the context into the next chunk. The trade-off is repeated body text.

Strategy B starts with paragraph boundaries. It groups adjacent paragraphs when they fit and splits a long paragraph when needed. This keeps related sentences together where the source has clear paragraph breaks. Strategy C groups sentences and puts the article title at the start of each chunk. The title counts toward the same budget. It gives a passage some topic context when it appears on its own, at the cost of repeating the headline.

## Slide 9: Output and retrieval comparison

Across 3,152 articles, B produced the fewest chunks, at 15,914. That’s about 1,100 fewer than A, so there are fewer passages to embed. C was in between at 16,432.

Then M4 compared the three versions under the same dense retrieval settings. We counted a hit when one of the first five retrieved chunks matched annotated evidence. B and C hit on 23 out of 24 questions, and A hit on 21. So B matched C on Hit@5 while producing fewer chunks in this run. The questions came from eight science articles, which limits what we can conclude about other topics.

## Slide 10: Handoff to M3

We hand off one JSONL file per strategy, with one chunk per line. Each record contains the text that M3 embeds, a chunk ID for the passage, and a document ID linking it back to the article. We also keep the original URL, title, and publication time for citations. The matching manifest records the settings, counts, and file checksums, so the team can check which version was used. From here, M3 can turn the passages into vectors and preserve the source information alongside them.
