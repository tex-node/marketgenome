#!/usr/bin/env bash
set -euo pipefail

ROOT="${MARKET_GENOME_ROOT:-/opt/market-genome}"
COMPOSE_FILE="$ROOT/app/infrastructure/deployment/vps/docker-compose.vps.yml"
ENV_FILE="${MARKET_GENOME_ENV_FILE:-$ROOT/config/market-genome.env}"
PROJECT_NAME="${MARKET_GENOME_COMPOSE_PROJECT:-market-genome}"
DC=(docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

test "$(uname -s)" = "Linux"
command -v docker >/dev/null
docker compose version >/dev/null
test -d "$ROOT/app"
test -f "$ENV_FILE"
mkdir -p "$ROOT/data/raw" "$ROOT/data/canonical" "$ROOT/data/backups" "$ROOT/reports" "$ROOT/logs"
mkdir -p "$ROOT/data/postgres" "$ROOT/data/redis"
chmod 750 "$ROOT/data" "$ROOT/reports" "$ROOT/logs"
"${DC[@]}" config --quiet
"${DC[@]}" build api worker
"${DC[@]}" up -d --wait postgres redis
"${DC[@]}" exec -T postgres pg_isready -U "${POSTGRES_USER:-market_genome}" -d "${POSTGRES_DB:-market_genome}"
"${DC[@]}" run --rm worker python -m alembic -c infrastructure/alembic.ini upgrade head
"${DC[@]}" run --rm worker python scripts/verify_postgres_runtime.py
"${DC[@]}" up -d --wait api
"${DC[@]}" exec -T api python - <<'PY'
import urllib.request
urllib.request.urlopen("http://localhost:8000/health", timeout=10)
urllib.request.urlopen("http://localhost:8000/ready", timeout=10)
PY
echo '{"status":"COMPLETED","root":"'"$ROOT"'","postgres":"verified","api":"healthy"}'
