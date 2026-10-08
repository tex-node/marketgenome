# System overview

Market Genome is structured as a modular monorepo with an API, future worker/dashboard applications, and versioned packages for domain, ingestion, research engines, and shared infrastructure.

Phase 1 foundation includes:

- FastAPI service with health and readiness checks.
- PostgreSQL/TimescaleDB-ready schema for instruments, timeframes, sources, and price bars.
- CSV ingestion with deterministic validation and source hashing.
- Alembic migrations.
- Test scaffolding for ingestion, API, and migrations.

The platform is explicitly a research system. It does not claim predictive power until walk-forward validation and baseline comparison are implemented.

