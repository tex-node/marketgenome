#!/usr/bin/env bash
set -euo pipefail

ROOT="${MARKET_GENOME_ROOT:-/opt/market-genome}"
COMPOSE_FILE="$ROOT/app/infrastructure/deployment/vps/docker-compose.vps.yml"
ENV_FILE="${MARKET_GENOME_ENV_FILE:-$ROOT/config/market-genome.env}"
PROJECT_NAME="${MARKET_GENOME_COMPOSE_PROJECT:-market-genome}"
DC=(docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

"${DC[@]}" ps
"${DC[@]}" exec -T postgres pg_isready -U "${POSTGRES_USER:-market_genome}" -d "${POSTGRES_DB:-market_genome}"
"${DC[@]}" exec -T redis redis-cli ping
"${DC[@]}" run --rm worker python -m alembic -c infrastructure/alembic.ini current
"${DC[@]}" run --rm worker python scripts/verify_postgres_runtime.py
"${DC[@]}" exec -T api python - <<'PY'
import urllib.request
urllib.request.urlopen("http://localhost:8000/health", timeout=10)
urllib.request.urlopen("http://localhost:8000/ready", timeout=10)
PY
df -h "$ROOT/data" "$ROOT/reports"
test -w "$ROOT/data"
test -w "$ROOT/reports"
echo '{"status":"PASSED"}'
