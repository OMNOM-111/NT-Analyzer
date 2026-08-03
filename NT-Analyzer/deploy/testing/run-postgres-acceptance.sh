#!/usr/bin/env bash
# Isolated PostgreSQL acceptance runner for StratForge (Linux / macOS).
#
# Applies the additive migration set to an isolated, non-Production PostgreSQL
# instance and runs the PostgreSQL-dependent acceptance suite: migrations +
# checksum, RLS workspace isolation, UUID identity backfill, release-center
# tables and NinjaTrader resource leases / workers.
#
# Reads the two DSNs from the environment or from
# deploy/testing/postgres-acceptance.env. If they are absent it exits 3 with a
# clear BLOCKED message rather than pretending to pass.
#
# Never point these DSNs at a Production database — the suite truncates tables.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${here}/../.." && pwd)"
env_file="${1:-${here}/postgres-acceptance.env}"

if [[ -f "${env_file}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${env_file}"
  set +a
fi

if [[ -z "${STRATFORGE_TEST_POSTGRES_ADMIN_URL:-}" || -z "${STRATFORGE_TEST_POSTGRES_URL:-}" ]]; then
  echo "BLOCKED - EXTERNAL TEST DATABASE REQUIRED"
  echo "Set STRATFORGE_TEST_POSTGRES_ADMIN_URL and STRATFORGE_TEST_POSTGRES_URL"
  echo "(see postgres-acceptance.env.example and provision-test-postgres.sql)."
  exit 3
fi

cd "${repo_root}"

echo "== Applying migrations to the isolated acceptance database =="
python -c "from app.production_storage.core import MigrationRunner; import json, os; print(json.dumps(MigrationRunner(os.environ['STRATFORGE_TEST_POSTGRES_ADMIN_URL']).apply()))"

echo "== Running PostgreSQL-dependent acceptance suite =="
exec python -m pytest -q -p no:cacheprovider \
  tests/test_stage8_postgresql.py \
  tests/test_production_storage.py \
  tests/test_production_workers.py
