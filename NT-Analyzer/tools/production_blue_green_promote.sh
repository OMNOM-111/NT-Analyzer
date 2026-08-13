#!/usr/bin/env bash
# Production blue-green promotion for an already production-signed artifact.
# This script is inert unless explicitly invoked by the Release Center executor.
set -Eeuo pipefail
umask 077

: "${RELEASE_DIR:?RELEASE_DIR is required}"
BASE="${BASE:-/home/stratforge/production_data}"
LIVE_URL="${LIVE_URL:-http://127.0.0.1:18767/api/health/live}"
READY_URL="${READY_URL:-http://127.0.0.1:18767/api/health/ready}"
HEALTH_TIMEOUT_SEC="${HEALTH_TIMEOUT_SEC:-90}"
TRUSTED_SIGNING_KEY_PATH="${TRUSTED_SIGNING_KEY_PATH:-$BASE/config/canary-trusted-signing-key.json}"
PROD_ENV="${PROD_ENV:-$BASE/config/production-app.env}"
CONF="${CONF:-$BASE/config/supervisord.conf}"
ACTIVE="${ACTIVE:-$BASE/config/active-release}"
PROD_PROGRAMS="${PROD_PROGRAMS:-api-app worker operations telegram}"
EVIDENCE="$BASE/runtime/prod-promote-evidence"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$BASE/backups/prod-promote-$STAMP"

test "$(id -u)" = 0
case "$(realpath "$RELEASE_DIR")" in "$BASE/releases/"*) ;; *) echo "REFUSING: release outside immutable release root" >&2; exit 1;; esac
test -f "$RELEASE_DIR/manifest.json"; test -f "$RELEASE_DIR/manifest.sig"; test -x "$RELEASE_DIR/.venv/bin/python"
test -f "$PROD_ENV"; test -f "$CONF"; test ! -e "$BACKUP"
test "$(readlink -f /home/stratforge/canary-current)" = "$(realpath "$RELEASE_DIR")"
mkdir -p "$EVIDENCE"

verify_json="$(python3 "$RELEASE_DIR/tools/canary_manifest_trust.py" "$RELEASE_DIR" "$TRUSTED_SIGNING_KEY_PATH" --required-environment production)"
eval "$(python3 -c '
import json, shlex, sys
d=json.load(sys.stdin)
for k in ("version","channel","build_id","git_commit_sha","build_timestamp_utc","artifact_sha256"):
 print("NEW_"+k.upper()+"="+shlex.quote(str(d[k])))
' <<<"$verify_json")"
[[ "$NEW_CHANNEL" =~ ^(beta|stable)$ ]]
[[ "$NEW_GIT_COMMIT_SHA" =~ ^[0-9a-fA-F]{40,64}$ ]]
if [ -n "${EXPECTED_VERSION:-}" ]; then test "$EXPECTED_VERSION" = "$NEW_VERSION"; fi
if [ -n "${EXPECTED_CHANNEL:-}" ]; then test "$EXPECTED_CHANNEL" = "$NEW_CHANNEL"; fi
if [ -n "${EXPECTED_GIT_COMMIT_SHA:-}" ]; then test "$EXPECTED_GIT_COMMIT_SHA" = "$NEW_GIT_COMMIT_SHA"; fi

current_before="$(readlink -f /home/stratforge/current)"
test -n "$current_before"
mkdir "$BACKUP"; chmod 0700 "$BACKUP"
install -o stratforge -g root -m 0600 "$PROD_ENV" "$BACKUP/production-app.env.before"
printf '%s\n' "$current_before" >"$BACKUP/current.before"
readlink -f /home/stratforge/previous >"$BACKUP/previous.before" 2>/dev/null || : >"$BACKUP/previous.before"
cp -a "$ACTIVE" "$BACKUP/active-release.before"
chmod 0400 "$BACKUP/current.before" "$BACKUP/previous.before" "$BACKUP/active-release.before"

python3 - "$PROD_ENV" "$BACKUP/production-app.env.after" "$NEW_VERSION" "$NEW_CHANNEL" "$NEW_BUILD_ID" "$NEW_GIT_COMMIT_SHA" "$NEW_ARTIFACT_SHA256" "$NEW_BUILD_TIMESTAMP_UTC" <<'PY'
import pathlib, sys
source,target,version,channel,build_id,git_sha,artifact_sha,build_ts=sys.argv[1:9]
updates={"STRATFORGE_BUILD_VERSION":version,"APP_VERSION":version,"RELEASE_CHANNEL":channel,
 "BUILD_ID":build_id,"GIT_COMMIT_SHA":git_sha,"ARTIFACT_SHA256":artifact_sha.upper(),
 "BUILD_TIMESTAMP_UTC":build_ts,"STRATFORGE_BUILD_DATE":build_ts[:10],"DIRTY":"0"}
lines=pathlib.Path(source).read_text(encoding="utf-8").splitlines(); seen=set(); out=[]
for line in lines:
 key=line.split("=",1)[0] if "=" in line and not line.lstrip().startswith("#") else ""
 if key in updates: out.append(f"{key}={updates[key]}"); seen.add(key)
 else: out.append(line)
for key,value in updates.items():
 if key not in seen: out.append(f"{key}={value}")
pathlib.Path(target).write_text("\n".join(out)+"\n", encoding="utf-8")
PY
chmod 0400 "$BACKUP/production-app.env.after"

rollback() {
  install -o stratforge -g root -m 0600 "$BACKUP/production-app.env.before" "$PROD_ENV"
  ln -sfn "$(cat "$BACKUP/current.before")" /home/stratforge/current.new
  mv -Tf /home/stratforge/current.new /home/stratforge/current
  cp -a "$BACKUP/active-release.before" "$ACTIVE"
  supervisorctl -c "$CONF" restart $PROD_PROGRAMS >/dev/null 2>&1 || true
  exit 1
}
trap rollback ERR

install -o stratforge -g root -m 0600 "$BACKUP/production-app.env.after" "$PROD_ENV"
ln -sfn "$RELEASE_DIR" /home/stratforge/current.new
mv -Tf /home/stratforge/current.new /home/stratforge/current
basename "$RELEASE_DIR" >"$ACTIVE"; chown stratforge:root "$ACTIVE"; chmod 0644 "$ACTIVE"
supervisorctl -c "$CONF" restart $PROD_PROGRAMS >/dev/null

deadline=$((SECONDS + HEALTH_TIMEOUT_SEC)); live=""; ready=""
while [ "$SECONDS" -lt "$deadline" ]; do
  live="$(curl -fsS --max-time 3 -H 'Host: app.stratforges.com' -H 'X-Forwarded-Proto: https' "$LIVE_URL" || true)"
  grep -q "$NEW_GIT_COMMIT_SHA" <<<"$live" && break
  sleep 1
done
grep -q "$NEW_GIT_COMMIT_SHA" <<<"$live"
while [ "$SECONDS" -lt "$deadline" ]; do
  ready="$(curl -sS --max-time 8 -H 'Host: app.stratforges.com' -H 'X-Forwarded-Proto: https' "$READY_URL" || true)"
  if grep -q '"status": "ready"' <<<"$ready" && grep -q "$NEW_GIT_COMMIT_SHA" <<<"$ready" \
    && grep -q '"live_trading_allowed": false' <<<"$ready" && grep -q '"real_payments_allowed": false' <<<"$ready"; then break; fi
  sleep 2
done
grep -q '"status": "ready"' <<<"$ready"; grep -q "$NEW_GIT_COMMIT_SHA" <<<"$ready"
grep -q '"live_trading_allowed": false' <<<"$ready"; grep -q '"real_payments_allowed": false' <<<"$ready"
trap - ERR
if [ "$current_before" != "$RELEASE_DIR" ]; then
  ln -sfn "$current_before" /home/stratforge/previous.new
  mv -Tf /home/stratforge/previous.new /home/stratforge/previous
fi

result="$EVIDENCE/prod-promote-$NEW_VERSION-$STAMP.json"
python3 - "$result" "$NEW_VERSION" "$NEW_CHANNEL" "$NEW_BUILD_ID" "$NEW_GIT_COMMIT_SHA" "$NEW_ARTIFACT_SHA256" <<'PY'
import json,pathlib,sys
path,version,channel,build_id,git_sha,artifact_sha=sys.argv[1:]
pathlib.Path(path).write_text(json.dumps({"ok":True,"environment":"production","version":version,
 "channel":channel,"build_id":build_id,"git_commit_sha":git_sha,"artifact_sha256":artifact_sha.upper(),
 "same_artifact_as_canary":True,"live_trading_allowed":False,"real_payments_allowed":False,
 "secrets_redacted":True},sort_keys=True,indent=2)+"\n",encoding="utf-8")
PY
chmod 0400 "$result"
cat "$result"
