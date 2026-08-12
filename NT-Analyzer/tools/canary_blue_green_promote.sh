#!/usr/bin/env bash
# Real blue-green executor for the Canary-only slot on the actual
# Supervisor-managed production host (no systemd). Atomically switches the
# `canary-current`/`canary-previous` symlinks to a new, already-extracted
# and signature-verified release directory, restarts only the Canary
# Supervisor programs, verifies health, and automatically rolls back on any
# failure after the switch point. Production's `current`/`previous`
# symlinks and `api-app`/`worker`/`operations`/`telegram` programs are never
# touched by this script.
#
# Required environment variables (no defaults, fail closed if unset):
#   RELEASE_DIR             Absolute path to the extracted, verified release
#                           (e.g. $BASE/releases/0.10.0-beta.1-<sha>)
#   NEW_VERSION             e.g. 0.10.0-beta.1
#   NEW_CHANNEL             beta|stable
#   NEW_BUILD_ID
#   NEW_GIT_COMMIT_SHA
#   NEW_ARTIFACT_SHA256
#   NEW_BUILD_TIMESTAMP_UTC ISO-8601 UTC, e.g. 2026-08-11T20:00:00Z
#
# Optional overrides:
#   BASE (default /home/stratforge/production_data)
#   HEALTH_URL (default https://canary.stratforges.com/api/health/ready)
#   HEALTH_TIMEOUT_SEC (default 60)
set -Eeuo pipefail
umask 077

: "${RELEASE_DIR:?RELEASE_DIR is required}"
: "${NEW_VERSION:?NEW_VERSION is required}"
: "${NEW_CHANNEL:?NEW_CHANNEL is required}"
: "${NEW_BUILD_ID:?NEW_BUILD_ID is required}"
: "${NEW_GIT_COMMIT_SHA:?NEW_GIT_COMMIT_SHA is required}"
: "${NEW_ARTIFACT_SHA256:?NEW_ARTIFACT_SHA256 is required}"
: "${NEW_BUILD_TIMESTAMP_UTC:?NEW_BUILD_TIMESTAMP_UTC is required}"

BASE="${BASE:-/home/stratforge/production_data}"
HEALTH_URL="${HEALTH_URL:-https://canary.stratforges.com/api/health/ready}"
HEALTH_TIMEOUT_SEC="${HEALTH_TIMEOUT_SEC:-60}"
config="$BASE/config"
conf="$config/supervisord.conf"
canary_env="$config/canary.env"
evidence="$BASE/runtime/canary-promote-evidence"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$BASE/backups/canary-promote-$stamp"
result="$evidence/canary-promote-$NEW_VERSION-$stamp.json"

test "$(id -u)" = 0
test -d "$RELEASE_DIR"
test -f "$RELEASE_DIR/manifest.json"
test -f "$RELEASE_DIR/manifest.sig"
test -f "$canary_env"
test ! -e "$backup"
mkdir -p "$evidence"

# --- verify manifest is a real production-trust, signed artifact ---
python3 - "$RELEASE_DIR" <<'PY'
import json, sys, pathlib
release = pathlib.Path(sys.argv[1])
manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
if manifest.get("trust_tier") != "production":
    raise SystemExit("REFUSING: manifest trust_tier is not 'production': " + str(manifest.get("trust_tier")))
signing = manifest.get("signing") or {}
if signing.get("algorithm") != "ECDSA_P256_SHA256_RAW":
    raise SystemExit("REFUSING: unexpected signing algorithm")
sig = (release / "manifest.sig").read_bytes()
if len(sig) != 64:
    raise SystemExit("REFUSING: manifest.sig has an unexpected length")
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
import base64

def _b64url_decode(value):
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded)

x = int.from_bytes(_b64url_decode(signing["public_key_x"]), "big")
y = int.from_bytes(_b64url_decode(signing["public_key_y"]), "big")
public_key = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
manifest_bytes = (release / "manifest.json").read_bytes()
r = int.from_bytes(sig[:32], "big")
s = int.from_bytes(sig[32:], "big")
public_key.verify(encode_dss_signature(r, s), manifest_bytes, ec.ECDSA(hashes.SHA256()))
print("manifest_signature_verified=true")
print("key_fingerprint=" + signing["key_fingerprint"])
PY

for service in api worker-canary operations-canary; do
  sudo -n supervisorctl -c "$conf" status "$service" >/dev/null 2>&1 || true
done

mkdir "$backup"
chmod 0700 "$backup"
install -o stratforge -g root -m 0600 "$canary_env" "$backup/canary.env.before"
readlink -f /home/stratforge/canary-current >"$backup/canary-current.before"
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
  sudo -n supervisorctl -c "$conf" restart api worker-canary operations-canary >/dev/null 2>&1 || true
  for n in $(seq 1 "$HEALTH_TIMEOUT_SEC"); do
    if curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null 2>&1; then exit 1; fi
    sleep 1
  done
  exit 1
}
trap rollback ERR

install -o stratforge -g root -m 0600 "$backup/canary.env.after" "$canary_env"
ln -sfn "$RELEASE_DIR" /home/stratforge/canary-current.new
mv -Tf /home/stratforge/canary-current.new /home/stratforge/canary-current
sudo -n supervisorctl -c "$conf" restart api worker-canary operations-canary >/dev/null

ready=""
for n in $(seq 1 "$HEALTH_TIMEOUT_SEC"); do
  ready="$(curl -fsS --max-time 5 "$HEALTH_URL" || true)"
  if grep -q "\"build_version\": \"$NEW_VERSION\"" <<<"$ready"; then break; fi
  sleep 1
done
grep -q "\"build_version\": \"$NEW_VERSION\"" <<<"$ready"
grep -q '"live_trading_allowed": false' <<<"$ready"
grep -q '"real_payments_allowed": false' <<<"$ready"

trap - ERR
python3 - "$result" "$backup" "$NEW_VERSION" "$NEW_BUILD_ID" "$NEW_ARTIFACT_SHA256" "$NEW_GIT_COMMIT_SHA" <<'PY'
import json, pathlib, sys
result, backup, version, build_id, artifact_sha, git_sha = sys.argv[1:7]
pathlib.Path(result).write_text(json.dumps({
    "ok": True,
    "version": version,
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
