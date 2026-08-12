#!/usr/bin/env bash
# Backup + restore round-trip for the isolated PostgreSQL acceptance database.
#
# Proves the schema + data can be dumped and restored into a fresh database
# (disaster-recovery drill) WITHOUT touching Production. Uses pg_dump custom
# format and pg_restore. Point BASE_ADMIN_URL at the maintenance database
# (e.g. .../postgres) so the acceptance DB can be dropped/recreated.
#
# Never run against a Production database.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
env_file="${1:-${here}/postgres-acceptance.env}"
[[ -f "${env_file}" ]] && { set -a; source "${env_file}"; set +a; }

: "${STRATFORGE_TEST_POSTGRES_ADMIN_URL:?set STRATFORGE_TEST_POSTGRES_ADMIN_URL}"
src_url="${STRATFORGE_TEST_POSTGRES_ADMIN_URL}"
# Maintenance DSN (defaults to the same server's 'postgres' database).
base_admin_url="${BASE_ADMIN_URL:-${src_url%/*}/postgres}"
restore_db="${RESTORE_DB:-stratforge_acceptance_restore}"
dump_file="${DUMP_FILE:-$(mktemp -t sf_acceptance.XXXXXX.dump)}"

echo "== Dumping acceptance database -> ${dump_file} =="
pg_dump --format=custom --no-owner --file="${dump_file}" "${src_url}"

echo "== Recreating ${restore_db} =="
psql "${base_admin_url}" -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS ${restore_db};"
psql "${base_admin_url}" -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${restore_db};"

restore_url="${base_admin_url%/*}/${restore_db}"
echo "== Restoring into ${restore_db} =="
pg_restore --no-owner --dbname="${restore_url}" "${dump_file}"

echo "== Verifying row counts survived the round-trip =="
psql "${restore_url}" -v ON_ERROR_STOP=1 -c "SELECT relname, n_live_tup FROM pg_stat_user_tables WHERE relname LIKE 'sf_%' ORDER BY relname;"

echo "OK - backup/restore round-trip completed for ${restore_db}"
