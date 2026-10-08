# ADR 0003: PostgreSQL storage

Decision: use PostgreSQL with TimescaleDB-compatible deployment.

Rationale: market bars are relational and time-series oriented. PostgreSQL also leaves room for pgvector and robust transactional metadata.

