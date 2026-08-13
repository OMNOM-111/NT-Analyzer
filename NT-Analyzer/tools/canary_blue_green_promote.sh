#!/usr/bin/env bash
# Real blue-green executor for the Canary-only slot on the actual
# Supervisor-managed production host (no systemd). Atomically switches the
# `canary-current`/`canary-previous` symlinks to a new, already-extracted
# release directory whose manifest is verified against a *pinned* trusted
# production public key (never the key embedded in the manifest itself),
# restarts only the Canary Supervisor programs that actually exist in
# `supervisord.conf`, verifies health, and automatically rolls back on any
# failure after the switch point. Production's `current`/`previous`
# symlinks and `api`/`worker`/`operations`/`telegram` programs are never
# touched by this script.
#
# The deployed version/channel/build ID/git SHA/artifact SHA are never
# accepted as independent caller-supplied values (that would let a caller
# deploy metadata that disagrees with what was actually signed and
# extracted). They are extracted exclusively from the verified, signed
# manifest by tools/canary_manifest_trust.py.
#
# Required environment variables (no defaults, fail closed if unset):
#   RELEASE_DIR             Absolute path to the extracted, verified release
#                           (e.g. $BASE/releases/0.10.0-beta.1-<sha>)
#
# Optional overrides:
#   BASE (default /home/stratforge/production_data)
#   HEALTH_URL (default https://canary.stratforges.com/api/health/ready)
#   LIVE_URL (default HEALTH_URL with a trailing /ready replaced by /live)
#   HEALTH_TIMEOUT_SEC (default 60; overall deadline after the Supervisor restart)
#   LIVE_CURL_MAX_SEC (default 3)
#   READY_CURL_MAX_SEC (default 8)
#   TRUSTED_SIGNING_KEY_PATH (default $BASE/config/canary-trusted-signing-key.json)
#   LOCKDOWN_MARKER_PATH (default $BASE/config/canary-privilege-lockdown.ok.json;
#                    written only by tools/canary_isolation_provision.py
#                    --lockdown-privileges after post-migration privilege
#                    revocation succeeds)
#   CANARY_PROGRAMS (default "api worker-canary operations-canary", plus
#                    `telegram-canary` only when Canary's protected Telegram
#                    token and webhook secret are present in canary.env;
#                    space-separated Supervisor program names
#                    this script must restart; every requested name must have
#                    a [program:NAME] section in supervisord.conf)
#   EXPECTED_VERSION / EXPECTED_CHANNEL (optional operator sanity check: if
#                    set, must match the manifest-derived value or the
#                    script refuses before touching anything)
set -Eeuo pipefail
umask 077

: "${RELEASE_DIR:?RELEASE_DIR is required}"

BASE="${BASE:-/home/stratforge/production_data}"
HEALTH_URL="${HEALTH_URL:-https://canary.stratforges.com/api/health/ready}"
LIVE_URL="${LIVE_URL:-${HEALTH_URL%/ready}/live}"
HEALTH_TIMEOUT_SEC="${HEALTH_TIMEOUT_SEC:-60}"
LIVE_CURL_MAX_SEC="${LIVE_CURL_MAX_SEC:-3}"
READY_CURL_MAX_SEC="${READY_CURL_MAX_SEC:-8}"
TRUSTED_SIGNING_KEY_PATH="${TRUSTED_SIGNING_KEY_PATH:-$BASE/config/canary-trusted-signing-key.json}"
LOCKDOWN_MARKER_PATH="${LOCKDOWN_MARKER_PATH:-$BASE/config/canary-privilege-lockdown.ok.json}"
canary_telegram_configured=false
if grep -qE '^NTA_TELEGRAM_BOT_TOKEN=.+$' "$canary_env" \
   && grep -qE '^NTA_TELEGRAM_WEBHOOK_SECRET=.+$' "$canary_env"; then
  canary_telegram_configured=true
fi
if [ -z "${CANARY_PROGRAMS:-}" ]; then
  CANARY_PROGRAMS="api worker-canary operations-canary"
  if [ "$canary_telegram_configured" = true ]; then
    CANARY_PROGRAMS="$CANARY_PROGRAMS telegram-canary"
  fi
fi
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
config="$BASE/config"
conf="$config/supervisord.conf"
canary_env="$config/canary.env"
evidence="$BASE/runtime/canary-promote-evidence"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$BASE/backups/canary-promote-$stamp"

test "$(id -u)" = 0
test -d "$RELEASE_DIR"
test -f "$RELEASE_DIR/manifest.json"
test -f "$RELEASE_DIR/manifest.sig"
test -f "$canary_env"
test -f "$conf"
test -f "$LOCKDOWN_MARKER_PATH"
test ! -e "$backup"
mkdir -p "$evidence"

ensure_canary_telegram_supervisor_program() {
  local launcher_source="$RELEASE_DIR/deploy/canary/run-telegram-canary.sh.example"
  local launcher_target="$config/run-telegram-canary.sh"
  test -f "$launcher_source"
  install -o stratforge -g root -m 0700 "$launcher_source" "$launcher_target"
  if grep -qE '^\[program:telegram-canary\]' "$conf"; then
    return 0
  fi
  local conf_backup="$config/supervisord.conf.before-telegram-canary-$stamp"
  install -o root -g root -m 0600 "$conf" "$conf_backup"
  cat >>"$conf" <<'EOF'

[program:telegram-canary]
command=/home/stratforge/production_data/config/run-telegram-canary.sh
user=stratforge
priority=80
autostart=true
autorestart=true
startsecs=5
startretries=10
stopsignal=TERM
stopwaitsecs=90
stopasgroup=true
killasgroup=true
redirect_stderr=true
stdout_logfile=/home/stratforge/production_data/logs/telegram-canary.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=5
environment=HOME="/home/stratforge"
EOF
}

if [[ " $CANARY_PROGRAMS " = *" telegram-canary "* ]]; then
  ensure_canary_telegram_supervisor_program
fi

python3 - "$LOCKDOWN_MARKER_PATH" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
try:
  marker = json.loads(path.read_text(encoding="utf-8"))
except Exception as exc:
  raise SystemExit("REFUSING: Canary privilege-lockdown marker is unreadable") from exc
if not isinstance(marker, dict) or marker.get("schema_version") != 1 or marker.get("ok") is not True:
  raise SystemExit("REFUSING: Canary privilege-lockdown marker is invalid")
if not str(marker.get("canary_database_name") or "").strip():
  raise SystemExit("REFUSING: Canary privilege-lockdown marker has no database name")
if not str(marker.get("canary_app_role") or "").strip():
  raise SystemExit("REFUSING: Canary privilege-lockdown marker has no app role")
revoked = set(marker.get("revoked_from") or [])
if "PUBLIC" not in revoked:
  raise SystemExit("REFUSING: Canary privilege-lockdown marker does not record PUBLIC revocation")
PY

# --- verify manifest against the pinned trusted key; derive identity ---
verify_json="$(python3 "$script_dir/canary_manifest_trust.py" \
  "$RELEASE_DIR" "$TRUSTED_SIGNING_KEY_PATH" --required-environment canary)"
echo "$verify_json"

eval "$(python3 -c '
import json, shlex, sys
data = json.load(sys.stdin)
for key in ("version", "channel", "build_id", "git_commit_sha", "build_timestamp_utc", "artifact_sha256", "key_fingerprint"):
    print("NEW_" + key.upper() + "=" + shlex.quote(str(data[key])))
' <<<"$verify_json")"

[[ "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || { echo "REFUSING: NEW_VERSION has an unexpected shape" >&2; exit 1; }
[[ "$NEW_CHANNEL" =~ ^(beta|stable)$ ]] || { echo "REFUSING: NEW_CHANNEL must be beta or stable" >&2; exit 1; }
[[ "$NEW_BUILD_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$ ]] || { echo "REFUSING: NEW_BUILD_ID has an unexpected shape" >&2; exit 1; }
[[ "$NEW_GIT_COMMIT_SHA" =~ ^[0-9a-fA-F]{40,64}$ ]] || { echo "REFUSING: NEW_GIT_COMMIT_SHA has an unexpected shape" >&2; exit 1; }
[[ "$NEW_ARTIFACT_SHA256" =~ ^[0-9a-f]{64}$ ]] || { echo "REFUSING: NEW_ARTIFACT_SHA256 has an unexpected shape" >&2; exit 1; }

if [ -n "${EXPECTED_VERSION:-}" ] && [ "$EXPECTED_VERSION" != "$NEW_VERSION" ]; then
  echo "REFUSING: EXPECTED_VERSION=$EXPECTED_VERSION does not match manifest version=$NEW_VERSION" >&2
  exit 1
fi
if [ -n "${EXPECTED_CHANNEL:-}" ] && [ "$EXPECTED_CHANNEL" != "$NEW_CHANNEL" ]; then
  echo "REFUSING: EXPECTED_CHANNEL=$EXPECTED_CHANNEL does not match manifest channel=$NEW_CHANNEL" >&2
  exit 1
fi

result="$evidence/canary-promote-$NEW_VERSION-$stamp.json"

# --- resolve the real Canary Supervisor program topology; never assume ---
# Every requested `[program:NAME]` section must be present in the current
# supervisord.conf. Skipping a missing worker/operations program would let a
# partial topology pass promotion while old or absent worker processes remain
# invisible until runtime symptoms appear.
mapfile -t defined_programs < <(grep -oE '^\[program:[^]]+\]' "$conf" | sed -E 's/^\[program:(.*)\]$/\1/')
restart_targets=()
missing_targets=()
for requested in $CANARY_PROGRAMS; do
  found=""
  for defined in "${defined_programs[@]}"; do
    if [ "$defined" = "$requested" ]; then
      restart_targets+=("$requested")
      found="1"
      break
    fi
  done
  if [ -z "$found" ]; then
    missing_targets+=("$requested")
  fi
done
if [ "${#missing_targets[@]}" -ne 0 ]; then
  echo "REFUSING: required Canary Supervisor program(s) missing from $conf: ${missing_targets[*]}" >&2
  exit 1
fi
echo "canary_restart_targets=${restart_targets[*]}"

mkdir "$backup"
chmod 0700 "$backup"
install -o stratforge -g root -m 0600 "$canary_env" "$backup/canary.env.before"
current_before="$(readlink -f /home/stratforge/canary-current 2>/dev/null || true)"
if [ -z "$current_before" ]; then
  echo "REFUSING: /home/stratforge/canary-current must exist before blue-green promotion so rollback has a target" >&2
  exit 1
fi
printf '%s\n' "$current_before" >"$backup/canary-current.before"
readlink -f /home/stratforge/canary-previous >"$backup/canary-previous.before" 2>/dev/null || echo "" >"$backup/canary-previous.before"
chmod 0400 "$backup/canary-current.before" "$backup/canary-previous.before"

python3 - "$canary_env" "$backup/canary.env.after" \
  "$NEW_VERSION" "$NEW_CHANNEL" "$NEW_BUILD_ID" "$NEW_GIT_COMMIT_SHA" \
  "$NEW_ARTIFACT_SHA256" "$NEW_BUILD_TIMESTAMP_UTC" <<'PY'
import pathlib, sys
source, target, version, channel, build_id, git_sha, artifact_sha, build_ts = sys.argv[1:9]
updates = {
    "STRATFORGE_BUILD_VERSION": version,
    "APP_VERSION": version,
    "RELEASE_CHANNEL": channel,
    "BUILD_ID": build_id,
    "GIT_COMMIT_SHA": git_sha,
    "ARTIFACT_SHA256": artifact_sha.upper(),
    "BUILD_TIMESTAMP_UTC": build_ts,
    "STRATFORGE_BUILD_DATE": build_ts[:10],
    "DIRTY": "0",
}
lines = pathlib.Path(source).read_text(encoding="utf-8").splitlines()
seen, out = set(), []
for line in lines:
    key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else ""
    if key in updates:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")
pathlib.Path(target).write_text("\n".join(out) + "\n", encoding="utf-8")
PY
chmod 0400 "$backup/canary.env.after"

rollback() {
  echo "ROLLING_BACK" >&2
  install -o stratforge -g root -m 0600 "$backup/canary.env.before" "$canary_env"
  previous_target="$(cat "$backup/canary-current.before")"
  ln -sfn "$previous_target" /home/stratforge/canary-current.new
  mv -Tf /home/stratforge/canary-current.new /home/stratforge/canary-current
  sudo -n supervisorctl -c "$conf" restart "${restart_targets[@]}" >/dev/null 2>&1 || true
  for n in $(seq 1 "$HEALTH_TIMEOUT_SEC"); do
    if curl -fsS --max-time "$LIVE_CURL_MAX_SEC" "$LIVE_URL" >/dev/null 2>&1; then exit 1; fi
    sleep 1
  done
  exit 1
}
trap rollback ERR

install -o stratforge -g root -m 0600 "$backup/canary.env.after" "$canary_env"
old_target="$(cat "$backup/canary-current.before")"
ln -sfn "$RELEASE_DIR" /home/stratforge/canary-current.new
mv -Tf /home/stratforge/canary-current.new /home/stratforge/canary-current

# Pick up newly added/changed Canary Supervisor programs only after the
# symlink points at the new release. The previous Canary release may not be
# able to run split worker/operations programs at all.
sudo -n supervisorctl -c "$conf" reread >/dev/null
sudo -n supervisorctl -c "$conf" update >/dev/null
sudo -n supervisorctl -c "$conf" restart "${restart_targets[@]}" >/dev/null

# Identity is taken from /live (cheap, no control-plane probes). /ready is
# polled only after the new git SHA is visible, with a per-request timeout
# smaller than the remaining deadline so retries cannot overlap forever.
deadline=$((SECONDS + HEALTH_TIMEOUT_SEC))
live=""
while [ "$SECONDS" -lt "$deadline" ]; do
  live="$(curl -fsS --max-time "$LIVE_CURL_MAX_SEC" "$LIVE_URL" || true)"
  if grep -q "$NEW_GIT_COMMIT_SHA" <<<"$live"; then
    break
  fi
  sleep 1
done
if ! grep -q "$NEW_GIT_COMMIT_SHA" <<<"$live"; then
  echo "REFUSING: new runtime identity was not observed on /live before the health deadline" >&2
  exit 1
fi

ready=""
while [ "$SECONDS" -lt "$deadline" ]; do
  # Do not use curl -f: a 503 body is still useful, and -f would hide it.
  ready="$(curl -sS --max-time "$READY_CURL_MAX_SEC" "$HEALTH_URL" || true)"
  if grep -q '"status": "ready"' <<<"$ready" \
    && grep -q "\"build_version\": \"$NEW_VERSION\"" <<<"$ready" \
    && grep -q '"live_trading_allowed": false' <<<"$ready" \
    && grep -q '"real_payments_allowed": false' <<<"$ready"; then
    break
  fi
  sleep 2
done
grep -q '"status": "ready"' <<<"$ready"
grep -q "\"build_version\": \"$NEW_VERSION\"" <<<"$ready"
grep -q '"live_trading_allowed": false' <<<"$ready"
grep -q '"real_payments_allowed": false' <<<"$ready"

trap - ERR

# Only after the swap is confirmed healthy: atomically point
# canary-previous at the release that was current immediately before this
# swap, so a later, independent rollback tool always has a real one-step-back
# target to refer to (never this run's own transient in-flight state).
if [ -n "$old_target" ] && [ "$old_target" != "$RELEASE_DIR" ]; then
  ln -sfn "$old_target" /home/stratforge/canary-previous.new
  mv -Tf /home/stratforge/canary-previous.new /home/stratforge/canary-previous
fi

python3 - "$result" "$backup" "$NEW_VERSION" "$NEW_BUILD_ID" "$NEW_ARTIFACT_SHA256" "$NEW_GIT_COMMIT_SHA" "$NEW_CHANNEL" <<'PY'
import json, pathlib, sys
result, backup, version, build_id, artifact_sha, git_sha, channel = sys.argv[1:8]
pathlib.Path(result).write_text(json.dumps({
    "ok": True,
    "version": version,
    "channel": channel,
    "build_id": build_id,
    "artifact_sha256": artifact_sha.upper(),
    "git_commit_sha": git_sha,
    "rollback_directory": backup,
    "live_trading_allowed": False,
    "real_payments_allowed": False,
    "secrets_redacted": True,
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
chmod 0400 "$result"
cat "$result"
