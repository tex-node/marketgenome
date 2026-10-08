# Vector search

The initial foundation does not include approximate vector search. Future implementations must expose an index abstraction so exact search, pgvector, FAISS, and HNSW can be compared.

Approximate search must not be treated as authoritative until recall is measured against exact search on representative datasets.

