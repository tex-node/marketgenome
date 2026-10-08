# Deployment

This foundation is local-development focused. Production deployment requires explicit environment variables, managed PostgreSQL/TimescaleDB, secrets management, API rate limiting, metrics, backups, and health/readiness probes.

Canonical production URL: `https://genome.fothlog.com`

DNS requirement: create a DNS record for `genome.fothlog.com` pointing to the selected production host after deployment. The exact record type depends on the host:

- `CNAME` for most managed app platforms.
- `A`/`AAAA` records for a fixed server IP.

The included Docker Compose file binds PostgreSQL and Redis to `127.0.0.1` so they are reachable by local services on the VPS but not exposed publicly. Use `POSTGRES_PORT` and `REDIS_PORT` in `.env` if default ports are already occupied.
