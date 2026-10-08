#!/usr/bin/env bash
set -euo pipefail

ROOT="${MARKET_GENOME_ROOT:-/opt/market-genome}"
COMPOSE_FILE="$ROOT/app/infrastructure/deployment/vps/docker-compose.vps.yml"
ENV_FILE="${MARKET_GENOME_ENV_FILE:-$ROOT/config/market-genome.env}"
PROJECT_NAME="${MARKET_GENOME_COMPOSE_PROJECT:-market-genome}"
BACKUP_DIR="${MARKET_GENOME_BACKUP_ROOT:-$ROOT/data/backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP="$BACKUP_DIR/market_genome_$STAMP.sql"
DC=(docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

mkdir -p "$BACKUP_DIR"
"${DC[@]}" exec -T postgres pg_dump -U "${POSTGRES_USER:-market_genome}" "${POSTGRES_DB:-market_genome}" > "$DUMP"
test -s "$DUMP"
sha256sum "$DUMP" > "$DUMP.sha256"
tar -C "$ROOT" -czf "$BACKUP_DIR/market_genome_reports_$STAMP.tgz" reports app/research/studies app/research/data/manifests
echo '{"status":"COMPLETED","dump":"'"$DUMP"'","sha256":"'"$DUMP.sha256"'"}'
