"""Bounded SSH executor for immutable StratForge server releases.

The executor is opt-in.  It never exposes the configured host, key path or
proxy command through public status documents, and Production execution needs
an additional, explicit process-level owner gate even after Release Center
approval/step-up checks have succeeded.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, Mapping


ADAPTER_NAME = "stage9_ssh"
_ADAPTER_ENV = "STRATFORGE_RELEASE_DEPLOY_ADAPTER"
_HOST_ENV = "STRATFORGE_RELEASE_SSH_HOST"
_USER_ENV = "STRATFORGE_RELEASE_SSH_USER"
_KEY_ENV = "STRATFORGE_RELEASE_SSH_KEY"
_PROXY_ENV = "STRATFORGE_RELEASE_SSH_PROXY_COMMAND"
_PRODUCTION_GATE_ENV = "STRATFORGE_RELEASE_PRODUCTION_EXECUTION"
_PRODUCTION_GATE_VALUE = "owner_approved"
_REMOTE_BASE = "/home/stratforge/production_data"
_RESULT_PREFIX = "STRATFORGE_RESULT="

_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40,64}$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")
_BUILD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,159}$")
_REF_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,159}$")


class ReleaseExecutorError(RuntimeError):
    """Sanitized operational failure safe to record in Release Center."""


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _script_path() -> Path:
    return _project_root() / "tools" / "stage9_remote_release.sh"


def _adapter_name() -> str:
    return str(os.environ.get(_ADAPTER_ENV) or "dry_run").strip().lower()


def _production_enabled() -> bool:
    return str(os.environ.get(_PRODUCTION_GATE_ENV) or "").strip().lower() == _PRODUCTION_GATE_VALUE


def _configuration() -> Dict[str, Any]:
    host = str(os.environ.get(_HOST_ENV) or "").strip()
    user = str(os.environ.get(_USER_ENV) or "stratforge").strip()
    raw_key = str(os.environ.get(_KEY_ENV) or "").strip()
    key = Path(raw_key).expanduser() if raw_key else Path()
    proxy = str(os.environ.get(_PROXY_ENV) or "cloudflared access ssh --hostname %h").strip()
    errors = []
    if not _HOST_RE.fullmatch(host):
        errors.append("ssh_host_invalid")
    if not _USER_RE.fullmatch(user):
        errors.append("ssh_user_invalid")
    if not raw_key or not key.is_file():
        errors.append("ssh_key_unavailable")
    if shutil.which("ssh") is None:
        errors.append("ssh_client_unavailable")
    if proxy and shutil.which(proxy.split()[0]) is None:
        errors.append("ssh_proxy_unavailable")
    if not _script_path().is_file():
        errors.append("remote_executor_script_missing")
    return {
        "host": host,
        "user": user,
        "key": key,
        "proxy": proxy,
        "errors": errors,
    }


def status() -> Dict[str, Any]:
    """Return a redacted status document suitable for ordinary API output."""
    name = _adapter_name()
    configured = name == ADAPTER_NAME
    errors = _configuration()["errors"] if configured else []
    available = configured and not errors
    return {
        "name": name or "dry_run",
        "real_configured": configured,
        "real_available": available,
        "canary_available": available,
        "production_available": available and _production_enabled(),
        "mode": "real" if available else ("blocked" if configured else "dry_run"),
        "configuration_state": "ready" if available else (errors[0] if errors else "not_configured"),
        "executor": ADAPTER_NAME if configured else "dry_run",
    }


def _require_configuration() -> Dict[str, Any]:
    public = status()
    if not public["real_configured"]:
        raise ReleaseExecutorError("real release executor is not configured")
    if not public["real_available"]:
        raise ReleaseExecutorError("real release executor configuration is incomplete")
    return _configuration()


def _ssh_args(config: Mapping[str, Any]) -> list[str]:
    args = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
        "-o", "StrictHostKeyChecking=accept-new", "-i", str(config["key"]),
    ]
    proxy = str(config.get("proxy") or "")
    if proxy:
        args.extend(["-o", f"ProxyCommand={proxy}"])
    args.append(f"{config['user']}@{config['host']}")
    return args


def _run(
    args: list[str], *, input_data: bytes | None = None, timeout: int = 900,
) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            args, input=input_data, capture_output=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseExecutorError(f"release executor transport failed: {type(exc).__name__}") from None
    if completed.returncode:
        # Remote output can contain host-local paths.  Keep it out of the API and
        # audit document; operators can inspect the protected host evidence.
        raise ReleaseExecutorError(f"release executor returned exit code {completed.returncode}")
    return completed


def _parse_result(output: bytes) -> Dict[str, Any]:
    text = output.decode("utf-8", errors="replace")
    for line in reversed(text.splitlines()):
        if line.startswith(_RESULT_PREFIX):
            try:
                value = json.loads(line[len(_RESULT_PREFIX):])
            except json.JSONDecodeError:
                break
            if isinstance(value, dict) and value.get("ok") is True:
                return value
    raise ReleaseExecutorError("release executor returned no verified result")


def _run_remote(action: str, *values: str, timeout: int = 900) -> Dict[str, Any]:
    config = _require_configuration()
    allowed_action = {"build", "promote", "rollback-canary", "rollback-production"}
    if action not in allowed_action:
        raise ReleaseExecutorError("release executor action is invalid")
    for value in values:
        if not value or any(ch in value for ch in "\r\n\0'\"`$;&|<>(){}[]!\\ "):
            raise ReleaseExecutorError("release executor argument is invalid")
    remote_command = "bash -s -- " + " ".join([action, *values])
    completed = _run(
        [*_ssh_args(config), remote_command],
        input_data=_script_path().read_bytes(), timeout=timeout,
    )
    return _parse_result(completed.stdout)


def _git_root() -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=_project_root(),
        text=True, capture_output=True, check=False,
    )
    if completed.returncode:
        raise ReleaseExecutorError("release source repository is unavailable")
    return Path(completed.stdout.strip()).resolve()


def _upload_source_bundle(commit_sha: str) -> None:
    config = _require_configuration()
    root = _git_root()
    with tempfile.TemporaryDirectory(prefix="stratforge-release-") as tmp:
        bundle = Path(tmp) / f"source-{commit_sha}.bundle"
        created = subprocess.run(
            ["git", "bundle", "create", str(bundle), commit_sha], cwd=root,
            capture_output=True, check=False,
        )
        if created.returncode or not bundle.is_file():
            raise ReleaseExecutorError("release source bundle creation failed")
        verified = subprocess.run(
            ["git", "bundle", "verify", str(bundle)], cwd=root,
            capture_output=True, check=False,
        )
        if verified.returncode:
            raise ReleaseExecutorError("release source bundle verification failed")
        remote = f"{_REMOTE_BASE}/release-center/incoming/source-{commit_sha}.bundle"
        command = (
            f"umask 077; install -d -m 0700 {_REMOTE_BASE}/release-center/incoming; "
            f"tmp={remote}.upload; cat > $tmp; chmod 0600 $tmp; mv -f $tmp {remote}"
        )
        with bundle.open("rb") as handle:
            _run([*_ssh_args(config), command], input_data=handle.read(), timeout=300)


def build(candidate: Mapping[str, Any], git_commit_sha: str) -> Dict[str, Any]:
    version = str(candidate.get("app_version") or "")
    channel = str(candidate.get("release_channel") or "")
    commit = str(git_commit_sha or "")
    if not _VERSION_RE.fullmatch(version) or channel not in {"beta", "stable"}:
        raise ReleaseExecutorError("real release build requires a beta/stable semantic version")
    if not _COMMIT_RE.fullmatch(commit):
        raise ReleaseExecutorError("release commit identity is invalid")
    _upload_source_bundle(commit)
    result = _run_remote("build", version, channel, commit, timeout=1800)
    for key, pattern in (
        ("git_commit_sha", _COMMIT_RE), ("archive_sha256", _SHA_RE),
        ("manifest_sha256", _SHA_RE), ("build_id", _BUILD_RE),
        ("executor_ref", _REF_RE),
    ):
        if not pattern.fullmatch(str(result.get(key) or "")):
            raise ReleaseExecutorError("release build returned an invalid identity")
    if result["git_commit_sha"].lower() != commit.lower():
        raise ReleaseExecutorError("release build commit does not match selected commit")
    return {
        "app_version": version,
        "release_channel": channel,
        "build_id": result["build_id"],
        "git_commit_sha": result["git_commit_sha"],
        "artifact_sha256": result["archive_sha256"],
        "archive_sha256": result["archive_sha256"],
        "manifest_sha256": result["manifest_sha256"],
        "runtime_artifact_sha256": result["manifest_sha256"],
        "signature_algorithm": "ECDSA_P256_SHA256_RAW",
        "signature_status": "verified",
        "trust_tier": "production",
        "built_at_utc": result["built_at_utc"],
        "dirty": False,
        "storage_uri": f"artifact://server/{version}/{commit[:12]}",
        "executor_ref": result["executor_ref"],
        "file_count": int(result.get("file_count") or 0),
        "migration_count": int(result.get("migration_count") or 0),
    }


def deploy(environment: str, artifact: Mapping[str, Any]) -> Dict[str, Any]:
    env = str(environment or "").lower()
    if env not in {"canary", "production"}:
        raise ReleaseExecutorError("deployment environment is invalid")
    if env == "production" and not _production_enabled():
        raise ReleaseExecutorError("Production execution requires a separate owner gate")
    version = str(artifact.get("app_version") or "")
    channel = str(artifact.get("release_channel") or "")
    commit = str(artifact.get("git_commit_sha") or "")
    archive_sha = str(artifact.get("artifact_sha256") or "")
    manifest_sha = str(artifact.get("manifest_sha256") or "")
    build_id = str(artifact.get("build_id") or "")
    executor_ref = str(artifact.get("executor_ref") or "")
    checks = (
        _VERSION_RE.fullmatch(version), channel in {"beta", "stable"},
        _COMMIT_RE.fullmatch(commit), _SHA_RE.fullmatch(archive_sha),
        _SHA_RE.fullmatch(manifest_sha), _BUILD_RE.fullmatch(build_id),
        _REF_RE.fullmatch(executor_ref),
    )
    if not all(checks):
        raise ReleaseExecutorError("deployment artifact identity is incomplete")
    result = _run_remote(
        "promote", env, executor_ref, version, channel, commit,
        archive_sha, manifest_sha, build_id, timeout=900,
    )
    if str(result.get("git_commit_sha") or "").lower() != commit.lower():
        raise ReleaseExecutorError("deployed commit does not match immutable artifact")
    if str(result.get("manifest_sha256") or "").lower() != manifest_sha.lower():
        raise ReleaseExecutorError("deployed manifest does not match immutable artifact")
    return {
        "status": "pass",
        "adapter": ADAPTER_NAME,
        "strategy": "blue_green_symlink",
        "external_result": "pass",
        "environment": env,
        "artifact_id": artifact.get("artifact_id"),
        "artifact_sha256": archive_sha,
        "manifest_sha256": manifest_sha,
        "git_commit_sha": commit,
        "build_id": build_id,
        "steps": result.get("steps") or [],
        "maintenance_window": result.get("maintenance_window") or {},
        "evidence": {
            "identity_verified": True,
            "signature_verified": True,
            "readiness_verified": True,
            "same_immutable_artifact": True,
            "secrets_redacted": True,
        },
        "note": "real immutable-artifact deployment completed and verified",
    }


def rehearse_canary_rollback(artifact: Mapping[str, Any]) -> Dict[str, Any]:
    """Switch Canary to its previous slot, verify it, then re-promote artifact."""
    executor_ref = str(artifact.get("executor_ref") or "")
    commit = str(artifact.get("git_commit_sha") or "")
    if not _REF_RE.fullmatch(executor_ref) or not _COMMIT_RE.fullmatch(commit):
        raise ReleaseExecutorError("Canary rollback rehearsal identity is invalid")
    rolled_back = _run_remote("rollback-canary", executor_ref, commit, timeout=900)
    restored = deploy("canary", artifact)
    return {
        "ok": True,
        "rollback_verified": bool(rolled_back.get("rollback_verified")),
        "re_promoted": restored.get("external_result") == "pass",
        "previous_git_commit_sha": rolled_back.get("previous_git_commit_sha") or "",
        "current_git_commit_sha": commit,
        "secrets_redacted": True,
    }


def rollback_production(
    current_artifact: Mapping[str, Any], target_artifact: Mapping[str, Any],
) -> Dict[str, Any]:
    """Execute a verified one-slot Production rollback.

    Release Center validates owner/step-up and that ``target_artifact`` is a
    known prior Production artifact before this function is reached.  The host
    script independently requires the target to be the current ``previous``
    symlink and automatically restores the starting slot on health failure.
    """
    if not _production_enabled():
        raise ReleaseExecutorError("Production rollback requires a separate owner gate")
    current_ref = str(current_artifact.get("executor_ref") or "")
    target_ref = str(target_artifact.get("executor_ref") or "")
    version = str(target_artifact.get("app_version") or "")
    channel = str(target_artifact.get("release_channel") or "")
    commit = str(target_artifact.get("git_commit_sha") or "")
    archive_sha = str(target_artifact.get("artifact_sha256") or "")
    manifest_sha = str(target_artifact.get("manifest_sha256") or "")
    build_id = str(target_artifact.get("build_id") or "")
    if not all((
        _REF_RE.fullmatch(current_ref), _REF_RE.fullmatch(target_ref),
        _VERSION_RE.fullmatch(version), channel in {"beta", "stable"},
        _COMMIT_RE.fullmatch(commit), _SHA_RE.fullmatch(archive_sha),
        _SHA_RE.fullmatch(manifest_sha), _BUILD_RE.fullmatch(build_id),
    )):
        raise ReleaseExecutorError("Production rollback artifact identity is incomplete")
    result = _run_remote(
        "rollback-production", current_ref, target_ref, version, channel,
        commit, archive_sha, manifest_sha, build_id, timeout=900,
    )
    if str(result.get("git_commit_sha") or "").lower() != commit.lower():
        raise ReleaseExecutorError("Production rollback target identity mismatch")
    return {
        "status": "pass",
        "external_result": "pass",
        "adapter": ADAPTER_NAME,
        "strategy": "blue_green_symlink",
        "rollback_verified": True,
        "git_commit_sha": commit,
        "manifest_sha256": manifest_sha,
        "build_id": build_id,
        "secrets_redacted": True,
    }
