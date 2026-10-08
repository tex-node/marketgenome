# ADR 0004: Vector index abstraction

Decision: hide vector search behind an abstraction in later phases.

Rationale: exact search, pgvector, FAISS, and HNSW need empirical comparison. Approximate search must be recall-tested before use in research conclusions.

