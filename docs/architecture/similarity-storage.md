# Similarity Storage

Similarity queries and matches are persisted for reproducibility.

`SimilarityQuery` stores the query window, method, configuration, hashes, candidate count, returned match count, status, elapsed time, and diagnostics.

`SimilarityMatch` stores one ranked candidate with:

- query and candidate window ids;
- normalized-pattern and Market DNA references where available;
- distance and similarity score;
- component scores;
- source and vector hashes;
- diagnostics proving future outcomes were not used.
