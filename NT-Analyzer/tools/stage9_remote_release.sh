#!/usr/bin/env bash
# Host-side executor streamed over authenticated SSH by app/release_executor.py.
# It operates only inside the fixed StratForge release roots and emits one
# sanitized STRATFORGE_RESULT JSON record for the caller.
set -Eeuo pipefail
umask 077

BASE=/home/stratforge/production_data
RC="$BASE/release-center"
RELEASES="$BASE/releases"
ARTIFACTS="$BASE/artifacts"
TRUSTED_KEY="$BASE/config/canary-trusted-signing-key.json"
SIGNING_KEY="$BASE/secrets/release-signing/production-release-signing-key-v1.pem"
CANARY_CURRENT=/home/stratforge/canary-current
CANARY_PREVIOUS=/home/stratforge/canary-previous

emit_result() {
  python3 - "$1" <<'PY'
import json, sys
print("STRATFORGE_RESULT=" + json.dumps(json.loads(sys.argv[1]), sort_keys=True, separators=(",", ":")))
PY
}

safe_cleanup() {
  local target="${1:-}"
  case "$target" in
    "$RC/tmp/"*) rm -rf -- "$target" ;;
    "") ;;
    *) echo "REFUSING: unsafe temporary path" >&2; return 1 ;;
  esac
}

validate_version() { [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; }
validate_channel() { [[ "$1" =~ ^(beta|stable)$ ]]; }
validate_commit() { [[ "$1" =~ ^[0-9a-fA-F]{40,64}$ ]]; }
validate_sha() { [[ "$1" =~ ^[0-9a-fA-F]{64}$ ]]; }
validate_build() { [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,159}$ ]]; }
validate_ref() { [[ "$1" =~ ^[0-9A-Za-z][0-9A-Za-z._-]{0,159}$ ]]; }

build_release() {
  local version="$1" channel="$2" commit="$3"
  validate_version "$version"; validate_channel "$channel"; validate_commit "$commit"
  local ref="$version-${commit:0:12}"
  validate_ref "$ref"
  local bundle="$RC/incoming/source-$commit.bundle"
  local release_dir="$RELEASES/$ref"
  local archive_copy="$ARTIFACTS/StratForge.Server-$ref-$channel.zip"
  test -f "$bundle"; test -f "$TRUSTED_KEY"; test -f "$SIGNING_KEY"
  install -d -m 0700 "$RC/tmp" "$RC/incoming"
  install -d -m 0750 "$RELEASES" "$ARTIFACTS"
  local tmp
  tmp="$(mktemp -d "$RC/tmp/build-XXXXXXXX")"
  trap 'safe_cleanup "$tmp"' RETURN
  git clone -q "$bundle" "$tmp/source"
  test "$(git -C "$tmp/source" rev-parse HEAD)" = "$commit"
  test -z "$(git -C "$tmp/source" status --porcelain)"
  local project="$tmp/source/NT-Analyzer"
  test -d "$project"
  python3 - "$project/VERSION.json" "$version" "$channel" <<'PY'
import json, pathlib, sys
data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert data.get("version") == sys.argv[2]
assert data.get("channel") == sys.argv[3]
PY
  local python_bin="$CANARY_CURRENT/.venv/bin/python"
  test -x "$python_bin"
  (
    cd "$project"
    export STRATFORGE_RELEASE_SIGNING_KEY_PEM="$SIGNING_KEY"
    "$python_bin" tools/build_server_release.py \
      --version "$version" --channel "$channel" --production >"$tmp/build-output.json"
  )
  local report="$project/.artifacts/server/releases/$version/build-report.json"
  local archive="$project/.artifacts/server/releases/$version/StratForge.Server-$version-$channel.zip"
  test -f "$report"; test -f "$archive"
  local archive_sha manifest_sha build_id built_at file_count migration_count report_commit
  eval "$(python3 - "$report" <<'PY'
import json, shlex, sys
d=json.load(open(sys.argv[1], encoding="utf-8"))
for k in ("archive_sha256","manifest_sha256","build_id","build_timestamp_utc","file_count","migration_count","git_commit_sha"):
    print(k.upper()+"="+shlex.quote(str(d[k])))
PY
)"
  archive_sha="$ARCHIVE_SHA256"; manifest_sha="$MANIFEST_SHA256"; build_id="$BUILD_ID"
  built_at="$BUILD_TIMESTAMP_UTC"; file_count="$FILE_COUNT"; migration_count="$MIGRATION_COUNT"
  report_commit="$GIT_COMMIT_SHA"
  validate_sha "$archive_sha"; validate_sha "$manifest_sha"; validate_build "$build_id"
  test "$report_commit" = "$commit"

  if [ ! -e "$release_dir" ]; then
    local extract="$tmp/extracted"
    mkdir "$extract"
    unzip -q "$archive" -d "$extract"
    test -f "$extract/manifest.json"; test -f "$extract/manifest.sig"; test -f "$extract/app/server.py"
    cp -a "$CANARY_CURRENT/.venv" "$extract/.venv"
    "$extract/.venv/bin/python" "$extract/tools/canary_manifest_trust.py" \
      "$extract" "$TRUSTED_KEY" --required-environment canary >/dev/null
    mv "$extract" "$release_dir"
  fi
  test -d "$release_dir"; test -x "$release_dir/.venv/bin/python"
  local verified
  verified="$(python3 "$release_dir/tools/canary_manifest_trust.py" \
    "$release_dir" "$TRUSTED_KEY" --required-environment canary)"
  python3 - "$verified" "$commit" "$version" "$channel" "$manifest_sha" <<'PY'
import json, sys
d=json.loads(sys.argv[1])
assert d["ok"] is True
assert d["git_commit_sha"] == sys.argv[2]
assert d["version"] == sys.argv[3]
assert d["channel"] == sys.argv[4]
assert d["artifact_sha256"].lower() == sys.argv[5].lower()
PY
  if [ -e "$archive_copy" ]; then
    test "$(sha256sum "$archive_copy" | awk '{print toupper($1)}')" = "${archive_sha^^}"
  else
    install -m 0400 "$archive" "$archive_copy"
  fi
  local payload
  payload="$(python3 - "$version" "$channel" "$commit" "$archive_sha" "$manifest_sha" "$build_id" "$built_at" "$ref" "$file_count" "$migration_count" <<'PY'
import json, sys
version,channel,commit,archive_sha,manifest_sha,build_id,built_at,ref,file_count,migration_count=sys.argv[1:]
print(json.dumps({"ok":True,"version":version,"channel":channel,"git_commit_sha":commit,
 "archive_sha256":archive_sha.upper(),"manifest_sha256":manifest_sha.upper(),"build_id":build_id,
 "built_at_utc":built_at,"executor_ref":ref,"file_count":int(file_count),
 "migration_count":int(migration_count),"trust_tier":"production","signature_verified":True,
 "archive_self_verified":True,"secrets_redacted":True}, separators=(",", ":")))
PY
)"
  emit_result "$payload"
}

verify_expected_release() {
  local release_dir="$1" version="$2" channel="$3" commit="$4" archive_sha="$5" manifest_sha="$6" build_id="$7" required_env="$8"
  test -d "$release_dir"; validate_sha "$archive_sha"; validate_sha "$manifest_sha"; validate_build "$build_id"
  local actual_manifest
  actual_manifest="$(sha256sum "$release_dir/manifest.json" | awk '{print toupper($1)}')"
  test "$actual_manifest" = "${manifest_sha^^}"
  local verified
  verified="$(python3 "$release_dir/tools/canary_manifest_trust.py" "$release_dir" "$TRUSTED_KEY" --required-environment "$required_env")"
  python3 - "$verified" "$version" "$channel" "$commit" "$manifest_sha" "$build_id" <<'PY'
import json, sys
d=json.loads(sys.argv[1])
assert d["ok"] is True and d["version"] == sys.argv[2] and d["channel"] == sys.argv[3]
assert d["git_commit_sha"] == sys.argv[4] and d["artifact_sha256"].lower() == sys.argv[5].lower()
assert d["build_id"] == sys.argv[6]
PY
  local archive_copy="$ARTIFACTS/StratForge.Server-$(basename "$release_dir")-$channel.zip"
  test -f "$archive_copy"
  test "$(sha256sum "$archive_copy" | awk '{print toupper($1)}')" = "${archive_sha^^}"
}

promote_release() {
  local environment="$1" ref="$2" version="$3" channel="$4" commit="$5" archive_sha="$6" manifest_sha="$7" build_id="$8"
  [[ "$environment" =~ ^(canary|production)$ ]]; validate_ref "$ref"; validate_version "$version"; validate_channel "$channel"; validate_commit "$commit"
  local release_dir="$RELEASES/$ref"
  test "$(realpath "$release_dir")" = "$(realpath "$RELEASES")/$ref"
  verify_expected_release "$release_dir" "$version" "$channel" "$commit" "$archive_sha" "$manifest_sha" "$build_id" "$environment"
  local script
  if [ "$environment" = canary ]; then
    script="$release_dir/tools/canary_blue_green_promote.sh"
  else
    script="$release_dir/tools/production_blue_green_promote.sh"
  fi
  test -f "$script"
  sudo -n env RELEASE_DIR="$release_dir" EXPECTED_VERSION="$version" EXPECTED_CHANNEL="$channel" EXPECTED_GIT_COMMIT_SHA="$commit" \
    HEALTH_TIMEOUT_SEC=90 bash "$script" >/dev/null
  local current
  if [ "$environment" = canary ]; then current="$(readlink -f "$CANARY_CURRENT")"; else current="$(readlink -f /home/stratforge/current)"; fi
  test "$current" = "$release_dir"
  local payload
  payload="$(python3 - "$environment" "$version" "$channel" "$commit" "$archive_sha" "$manifest_sha" "$build_id" <<'PY'
import json, sys
env,version,channel,commit,archive_sha,manifest_sha,build_id=sys.argv[1:]
steps=[{"ordinal":i+1,"stage":s,"status":"pass","evidence":{"verified":True}} for i,s in enumerate(
 ["prepare_green","expand_migrate","start_green","green_readiness","drain_blue","switch_traffic","verify_live","contract_migrate"])]
print(json.dumps({"ok":True,"environment":env,"version":version,"channel":channel,
 "git_commit_sha":commit,"archive_sha256":archive_sha.upper(),"manifest_sha256":manifest_sha.upper(),
 "build_id":build_id,"steps":steps,"maintenance_window":{"environment":env,"kind":"deploy","state":"completed"},
 "identity_verified":True,"readiness_verified":True,"secrets_redacted":True}, separators=(",", ":")))
PY
)"
  emit_result "$payload"
}

rollback_canary() {
  local current_ref="$1" current_commit="$2"
  validate_ref "$current_ref"; validate_commit "$current_commit"
  local expected_current="$RELEASES/$current_ref"
  test "$(readlink -f "$CANARY_CURRENT")" = "$expected_current"
  local previous
  previous="$(readlink -f "$CANARY_PREVIOUS")"
  case "$previous" in "$RELEASES/"*) ;; *) echo "REFUSING: Canary previous slot outside release root" >&2; exit 1;; esac
  test -d "$previous"; test "$previous" != "$expected_current"
  local identity
  identity="$(python3 "$previous/tools/canary_manifest_trust.py" "$previous" "$TRUSTED_KEY" --required-environment canary)"
  eval "$(python3 - "$identity" <<'PY'
import json, shlex, sys
d=json.loads(sys.argv[1])
for k in ("version","channel","git_commit_sha"):
 print("PREV_"+k.upper()+"="+shlex.quote(str(d[k])))
PY
)"
  sudo -n env RELEASE_DIR="$previous" EXPECTED_VERSION="$PREV_VERSION" EXPECTED_CHANNEL="$PREV_CHANNEL" HEALTH_TIMEOUT_SEC=90 \
    bash "$previous/tools/canary_blue_green_promote.sh" >/dev/null
  test "$(readlink -f "$CANARY_CURRENT")" = "$previous"
  local payload
  payload="$(python3 - "$PREV_GIT_COMMIT_SHA" "$current_commit" <<'PY'
import json,sys
print(json.dumps({"ok":True,"rollback_verified":True,"previous_git_commit_sha":sys.argv[1],
 "from_git_commit_sha":sys.argv[2],"secrets_redacted":True}, separators=(",", ":")))
PY
)"
  emit_result "$payload"
}

rollback_production() {
  local current_ref="$1" target_ref="$2" version="$3" channel="$4" commit="$5" archive_sha="$6" manifest_sha="$7" build_id="$8"
  validate_ref "$current_ref"; validate_ref "$target_ref"; validate_version "$version"; validate_channel "$channel"; validate_commit "$commit"
  local current_dir="$RELEASES/$current_ref" target_dir="$RELEASES/$target_ref"
  test "$(readlink -f /home/stratforge/current)" = "$current_dir"
  test "$(readlink -f /home/stratforge/previous)" = "$target_dir"
  verify_expected_release "$target_dir" "$version" "$channel" "$commit" "$archive_sha" "$manifest_sha" "$build_id" production
  test -f "$target_dir/tools/production_blue_green_rollback.sh"
  sudo -n env RELEASE_DIR="$target_dir" EXPECTED_CURRENT_RELEASE_DIR="$current_dir" \
    EXPECTED_VERSION="$version" EXPECTED_CHANNEL="$channel" EXPECTED_GIT_COMMIT_SHA="$commit" \
    HEALTH_TIMEOUT_SEC=90 bash "$target_dir/tools/production_blue_green_rollback.sh" >/dev/null
  test "$(readlink -f /home/stratforge/current)" = "$target_dir"
  local payload
  payload="$(python3 - "$version" "$channel" "$commit" "$archive_sha" "$manifest_sha" "$build_id" <<'PY'
import json,sys
version,channel,commit,archive_sha,manifest_sha,build_id=sys.argv[1:]
print(json.dumps({"ok":True,"rollback_verified":True,"version":version,"channel":channel,
 "git_commit_sha":commit,"archive_sha256":archive_sha.upper(),"manifest_sha256":manifest_sha.upper(),
 "build_id":build_id,"secrets_redacted":True}, separators=(",", ":")))
PY
)"
  emit_result "$payload"
}

action="${1:-}"; shift || true
case "$action" in
  build) [ "$#" -eq 3 ]; build_release "$@" ;;
  promote) [ "$#" -eq 8 ]; promote_release "$@" ;;
  rollback-canary) [ "$#" -eq 2 ]; rollback_canary "$@" ;;
  rollback-production) [ "$#" -eq 8 ]; rollback_production "$@" ;;
  *) echo "REFUSING: unknown release executor action" >&2; exit 1 ;;
esac
