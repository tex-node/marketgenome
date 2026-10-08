# VPS deployment package

This repository includes an isolated VPS deployment package for later explicit execution. It is not deployed by Codex.

Expected path:

```text
/opt/market-genome
```

Expected layout:

```text
/opt/market-genome/app
/opt/market-genome/data/raw
/opt/market-genome/data/canonical
/opt/market-genome/data/backups
/opt/market-genome/reports
/opt/market-genome/logs
```

Files:

- `infrastructure/deployment/vps/docker-compose.vps.yml`
- `infrastructure/deployment/vps/.env.example`
- `scripts/vps/bootstrap_market_genome.sh`
- `scripts/vps/verify_market_genome.sh`
- `scripts/vps/backup_market_genome.sh`
- `scripts/vps/run_yahoo_pilot.sh`

Security defaults:

- PostgreSQL and Redis have no public host port bindings.
- API binds to `127.0.0.1:8000` unless explicitly changed.
- `.env` is required and must not be committed.
- `POSTGRES_PASSWORD` must be changed from the example.
- The scripts do not modify firewall rules.
- Backups are written under the configured backup directory and checksummed.

Bootstrap sequence:

```bash
cd /opt/market-genome/app
cp infrastructure/deployment/vps/.env.example infrastructure/deployment/vps/.env
# edit .env first
bash scripts/vps/bootstrap_market_genome.sh
```

Verification:

```bash
bash scripts/vps/verify_market_genome.sh
```

Backup:

```bash
bash scripts/vps/backup_market_genome.sh
```
