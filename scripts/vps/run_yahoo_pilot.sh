#!/usr/bin/env bash
set -euo pipefail

ROOT="${MARKET_GENOME_ROOT:-/opt/market-genome}"
COMPOSE_FILE="$ROOT/app/infrastructure/deployment/vps/docker-compose.vps.yml"
ENV_FILE="${MARKET_GENOME_ENV_FILE:-$ROOT/config/market-genome.env}"
PROJECT_NAME="${MARKET_GENOME_COMPOSE_PROJECT:-market-genome}"
MANIFEST="research/data/manifests/yahoo_market_data_pilot_v1.yaml"
STUDY_MANIFEST="research/studies/yahoo_multi_asset_pilot_v1.yaml"
REPORT_DIR="$ROOT/reports/yahoo_multi_asset_pilot_v1"
DC=(docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

mkdir -p "$REPORT_DIR"
"${DC[@]}" run --rm worker python scripts/verify_postgres_runtime.py | tee "$REPORT_DIR/postgres_verification.json"
"${DC[@]}" run --rm worker market-genome data provider-smoke yahoo_finance_v1 --symbol SPY | tee "$REPORT_DIR/provider_smoke_spy.json"
"${DC[@]}" run --rm worker market-genome data fetch-yahoo "$MANIFEST" --dry-run | tee "$REPORT_DIR/acquisition_plan.json"
"${DC[@]}" run --rm worker market-genome data fetch-yahoo "$MANIFEST" | tee "$REPORT_DIR/acquisition_summary.json"
"${DC[@]}" run --rm worker market-genome data import-manifest "$MANIFEST" --dry-run | tee "$REPORT_DIR/data_quality_dry_run.json"
"${DC[@]}" run --rm worker market-genome data quality-report --manifest yahoo_market_data_pilot_v1 | tee "$REPORT_DIR/data_quality_before_import.json"
"${DC[@]}" run --rm worker market-genome data import-manifest "$MANIFEST" | tee "$REPORT_DIR/import_summary.json"
"${DC[@]}" run --rm worker market-genome data quality-report --manifest yahoo_market_data_pilot_v1 | tee "$REPORT_DIR/data_quality_after_import.json"
STUDY_ID="$("${DC[@]}" run --rm worker market-genome studies create "$STUDY_MANIFEST" | tee "$REPORT_DIR/study_create.txt" | sed -n 's/^study_id=\([^ ]*\).*/\1/p')"
"${DC[@]}" run --rm worker market-genome studies refresh-dataset "$STUDY_ID" | tee "$REPORT_DIR/study_refresh_dataset.txt"
"${DC[@]}" run --rm worker market-genome studies prepare-data "$STUDY_ID" --batch-size 100 | tee "$REPORT_DIR/study_prepare_data.txt"
"${DC[@]}" run --rm worker market-genome studies status "$STUDY_ID" | tee "$REPORT_DIR/study_status.txt"
"${DC[@]}" run --rm worker market-genome studies preflight "$STUDY_ID" | tee "$REPORT_DIR/study_preflight.txt"
echo '{"status":"PILOT_SEQUENCE_COMPLETE","stopped_before":"validation_final_test_lock_final_test","study_id":"'"$STUDY_ID"'"}'
