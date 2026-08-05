"""Typed StratForge deployment environment and startup safety gates.

There are three deployable environments:

development
    Private Windows development. Local SQLite/JSON/DPAPI and test-only
    features may be enabled explicitly.

production
    The central multi-user service. Startup is fail-closed and requires
    explicit resource identities.

canary
    The isolated pre-production service. It has the same fail-closed remote
    safety boundary as Production, but separate data, secrets and identities.

The historical staging value remains accepted as a compatibility QA profile,
but maps to the development deployment boundary and is not a third deployment
target.

Library calls retain the historical production fallback so imports and older
tests remain compatible. The real server entrypoint must call
assert_startup_safe(), which rejects an implicit environment.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from functools import lru_cache
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
from typing import Any, Dict, Iterable, Optional, Tuple
import urllib.parse


DEVELOPMENT = "development"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANARY = "canary"
PRODUCTION = "production"
STAGING = "staging"  # Legacy isolated-QA profile; deploys as DEVELOPMENT.
_VALID = {DEVELOPMENT, CANARY, PRODUCTION, STAGING}
_ENV_KEYS = ("DEPLOYMENT_ENV", "STRATFORGE_ENV", "NTA_APP_ENV", "NTA_ENV")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
_PRODUCTION_ROLES = {
    "all-in-one", "api", "worker", "telegram", "connector-control",
}
_EDGE_MODES = {"direct-local", "cloudflare-tunnel", "reverse-proxy"}
_RELEASE_CHANNELS = {"dev", "beta", "stable"}
_GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")
_ARTIFACT_SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class RuntimeEnvError(RuntimeError):
    def __init__(self, message: str, status: int = 503):
        super().__init__(message)
        self.status = int(status)


@dataclass(frozen=True)
class DeploymentConfig:
    environment: str
    runtime_profile: str
    environment_explicit: bool
    instance_id: str
    deployment_role: str
    config_profile: str
    build_version: str
    build_date: str
    build_id: str
    git_commit_sha: str
    artifact_sha256: str
    build_timestamp_utc: str
    dirty: bool
    release_channel: str
    release_status: str
    region: str
    bind_host: str
    allowed_hosts: Tuple[str, ...]
    public_origin: str
    edge_mode: str
    trusted_proxy_ips: Tuple[str, ...]
    readiness_min_free_mb: int
    api_max_inflight: int
    api_backlog: int
    api_max_body_bytes: int
    worker_poll_ms: int
    worker_shutdown_grace_sec: int
    data_root: str
    database_id: str
    queue_id: str
    object_storage_id: str
    telegram_bot_id: str
    cookie_namespace: str
    signing_key_id: str
    log_namespace: str
    live_trading_allowed: bool
    real_payments_allowed: bool

    def as_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["app_version"] = self.build_version
        payload["deployment_environment"] = self.environment
        return payload

    def public_dict(self) -> Dict[str, Any]:
        return {
            "environment": self.environment,
            "deployment_environment": self.environment,
            "runtime_profile": self.runtime_profile,
            "instance_id": self.instance_id,
            "deployment_role": self.deployment_role,
            "config_profile": self.config_profile,
            "build_version": self.build_version,
            "app_version": self.build_version,
            "build_date": self.build_date,
            "build_id": self.build_id,
            "git_commit_sha": self.git_commit_sha,
            "artifact_sha256": self.artifact_sha256,
            "build_timestamp_utc": self.build_timestamp_utc,
            "dirty": self.dirty,
            "release_channel": self.release_channel,
            "release_status": self.release_status,
            "region": self.region,
            "public_origin": self.public_origin,
            "live_trading_allowed": self.live_trading_allowed,
            "real_payments_allowed": self.real_payments_allowed,
        }


def _project_version_metadata() -> Dict[str, str]:
    path = Path(__file__).resolve().parent.parent / "VERSION.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeEnvError("VERSION.json отсутствует или повреждён.", 503) from exc
    if not isinstance(raw, dict) or int(raw.get("schema_version") or 0) != 1:
        raise RuntimeEnvError("VERSION.json имеет неподдерживаемую схему.", 503)
    allowed = {
        "schema_version", "version", "channel", "status", "build_date",
        "build_timestamp_utc",
    }
    if set(raw) - allowed:
        raise RuntimeEnvError("VERSION.json содержит неизвестные поля.", 503)
    return {name: str(raw.get(name) or "").strip() for name in allowed if name != "schema_version"}


def _compatible_text(
    names: Tuple[str, ...], *, normalize=lambda value: value,
) -> str:
    values = []
    for name in names:
        raw = str(os.environ.get(name) or "").strip()
        if raw:
            values.append((name, normalize(raw)))
    if not values:
        return ""
    if len({value for _, value in values}) != 1:
        visible = ", ".join(f"{name}={value}" for name, value in values)
        raise RuntimeEnvError(f"Конфликт build identity: {visible}.", 503)
    return values[0][1]


def _normalize_channel(value: str) -> str:
    channel = str(value or "").strip().lower()
    return {"development": "dev", "canary": "beta"}.get(channel, channel)


def _normalize_timestamp(value: str) -> str:
    raw = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeEnvError("BUILD_TIMESTAMP_UTC должен быть ISO-8601 timestamp.", 503) from exc
    if parsed.tzinfo is None:
        raise RuntimeEnvError("BUILD_TIMESTAMP_UTC должен содержать UTC offset.", 503)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z",
    )


@lru_cache(maxsize=1)
def _local_git_state() -> Tuple[str, bool]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=_PROJECT_ROOT, check=True,
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"], cwd=_PROJECT_ROOT, check=True,
            capture_output=True, text=True, timeout=5,
        ).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return "", True
    return revision, dirty


def _configured_dirty() -> Optional[bool]:
    values = []
    for name in ("DIRTY", "STRATFORGE_BUILD_DIRTY"):
        parsed = _optional_bool(name)
        if parsed is not None:
            values.append((name, parsed))
    if not values:
        return None
    if len({value for _, value in values}) != 1:
        raise RuntimeEnvError("Конфликт DIRTY и STRATFORGE_BUILD_DIRTY.", 503)
    return values[0][1]


def _release_identity(
    environment: str, *, required: bool,
) -> Tuple[str, str, str, str, str, str, str, str, bool]:
    defaults = _project_version_metadata()
    version = _compatible_text(("APP_VERSION", "STRATFORGE_BUILD_VERSION"))
    channel = _compatible_text(
        ("RELEASE_CHANNEL", "STRATFORGE_RELEASE_CHANNEL"),
        normalize=_normalize_channel,
    )
    build_timestamp = _compatible_text((
        "BUILD_TIMESTAMP_UTC", "STRATFORGE_BUILD_TIMESTAMP_UTC",
    ))
    legacy_build_date = str(os.environ.get("STRATFORGE_BUILD_DATE") or "").strip()
    if environment == DEVELOPMENT or not required:
        version = version or defaults.get("version", "")
        channel = channel or _normalize_channel(defaults.get("channel", "dev"))
        build_timestamp = (
            build_timestamp
            or defaults.get("build_timestamp_utc", "")
            or (f"{legacy_build_date}T00:00:00Z" if legacy_build_date else "")
            or (
                f"{defaults.get('build_date', '')}T00:00:00Z"
                if defaults.get("build_date", "") else ""
            )
        )
    elif required and (not version or not channel or not build_timestamp):
        raise RuntimeEnvError(
            "APP_VERSION, RELEASE_CHANNEL и BUILD_TIMESTAMP_UTC обязательны "
            "в Canary/Production.",
            503,
        )
    version_match = _SEMVER_RE.fullmatch(version)
    prerelease = (version_match.group(4) or "") if version_match else ""
    if not version_match or any(
        item.isdigit() and len(item) > 1 and item.startswith("0")
        for item in prerelease.split(".") if item
    ):
        raise RuntimeEnvError("APP_VERSION должен быть SemVer.", 503)
    if channel not in _RELEASE_CHANNELS:
        raise RuntimeEnvError(
            "RELEASE_CHANNEL должен быть dev, beta или stable.",
            503,
        )
    if environment == DEVELOPMENT and channel != "dev":
        raise RuntimeEnvError("Development может иметь только RELEASE_CHANNEL=dev.", 503)
    if environment in {CANARY, PRODUCTION} and required and channel not in {"beta", "stable"}:
        raise RuntimeEnvError("Canary/Production не может выдавать себя за dev build.", 503)
    build_timestamp = _normalize_timestamp(build_timestamp)
    build_date = build_timestamp[:10]
    if legacy_build_date and legacy_build_date != build_date:
        raise RuntimeEnvError(
            "STRATFORGE_BUILD_DATE конфликтует с BUILD_TIMESTAMP_UTC.", 503,
        )
    try:
        date.fromisoformat(build_date)
    except ValueError:
        raise RuntimeEnvError("STRATFORGE_BUILD_DATE должен быть YYYY-MM-DD.", 503) from None
    status = {
        "dev": "in_development",
        "beta": "pre_release",
        "stable": "ready",
    }[channel]
    git_commit = _compatible_text(("GIT_COMMIT_SHA", "STRATFORGE_GIT_COMMIT_SHA"))
    artifact_sha = _compatible_text((
        "ARTIFACT_SHA256", "STRATFORGE_ARTIFACT_SHA256",
    ), normalize=lambda value: value.upper())
    build_id = _compatible_text(("BUILD_ID", "STRATFORGE_BUILD_ID"))
    configured_dirty = _configured_dirty()
    if environment == DEVELOPMENT:
        detected_sha, detected_dirty = _local_git_state()
        if git_commit and detected_sha and git_commit.lower() != detected_sha.lower():
            raise RuntimeEnvError("GIT_COMMIT_SHA не совпадает с локальным checkout.", 503)
        git_commit = git_commit or detected_sha
        # Launchers snapshot dirty-state before application imports can render
        # tracked governance views or write runtime state. Direct library starts
        # without an explicit snapshot still inspect the live checkout.
        dirty = detected_dirty if configured_dirty is None else configured_dirty
        build_id = build_id or f"dev-{version}-{(git_commit or 'unknown')[:12]}"
    else:
        dirty = bool(configured_dirty)
    if required:
        missing = [
            name for name, value in (
                ("BUILD_ID", build_id),
                ("GIT_COMMIT_SHA", git_commit),
                ("ARTIFACT_SHA256", artifact_sha),
            ) if not value
        ]
        if configured_dirty is None:
            missing.append("DIRTY")
        if missing:
            raise RuntimeEnvError(
                "Build identity неполон: " + ", ".join(missing) + ".", 503,
            )
    if git_commit and not _GIT_SHA_RE.fullmatch(git_commit):
        raise RuntimeEnvError("GIT_COMMIT_SHA должен быть полным Git SHA.", 503)
    if artifact_sha and not _ARTIFACT_SHA_RE.fullmatch(artifact_sha):
        raise RuntimeEnvError("ARTIFACT_SHA256 должен быть SHA-256.", 503)
    if build_id and not _ID_RE.fullmatch(build_id):
        raise RuntimeEnvError("BUILD_ID содержит недопустимые символы.", 503)
    if environment != DEVELOPMENT and dirty:
        raise RuntimeEnvError("Dirty build запрещён в Canary/Production.", 503)
    return (
        version, build_date, channel, status, build_id, git_commit,
        artifact_sha, build_timestamp, dirty,
    )


def _normalize_env(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in ("prod", "live"):
        return PRODUCTION
    if raw in ("preprod", "pre-production"):
        return CANARY
    if raw in ("dev", "local"):
        return DEVELOPMENT
    if raw in ("stage", "qa", "test"):
        return STAGING
    if raw in _VALID:
        return raw
    raise RuntimeEnvError(f"Неизвестное окружение StratForge={raw!r}.", 503)


def _configured_environments() -> Tuple[Tuple[str, str], ...]:
    values = []
    for key in _ENV_KEYS:
        raw = str(os.environ.get(key) or "").strip()
        if raw:
            values.append((key, _normalize_env(raw)))
    if not values:
        return ()
    deployment_values = {
        DEVELOPMENT if value == STAGING else value for _, value in values
    }
    if len(deployment_values) != 1:
        visible = ", ".join(f"{key}={value}" for key, value in values)
        raise RuntimeEnvError(
            f"Конфликт переменных окружения StratForge: {visible}.", 503,
        )
    return tuple(values)


def environment_explicit() -> bool:
    return bool(_configured_environments())


def app_env() -> str:
    """Return the selected runtime profile.

    Staging is returned for a legacy staging input so older status consumers
    remain compatible. Use deployment_environment() for the actual
    canonical deployment boundary.
    """
    values = _configured_environments()
    if not values:
        return PRODUCTION
    priority = {key: index for index, key in enumerate(_ENV_KEYS)}
    return min(values, key=lambda item: priority[item[0]])[1]


def deployment_environment() -> str:
    profile = app_env()
    return DEVELOPMENT if profile == STAGING else profile


def is_development() -> bool:
    return deployment_environment() == DEVELOPMENT


def is_staging() -> bool:
    """Compatibility name for the isolated non-production boundary."""
    return is_development()


def is_canary() -> bool:
    return deployment_environment() == CANARY


def is_production() -> bool:
    return deployment_environment() == PRODUCTION


def _optional_bool(name: str) -> Optional[bool]:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return None
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise RuntimeEnvError(f"{name} должен быть true/false или 1/0.", 503)


def _compatible_bool(primary: str, legacy: str) -> bool:
    preferred = _optional_bool(primary)
    old = _optional_bool(legacy)
    if preferred is not None and old is not None and preferred != old:
        raise RuntimeEnvError(f"Конфликт {primary} и {legacy}.", 503)
    if preferred is not None:
        return preferred
    return bool(old)


def test_auth_enabled() -> bool:
    """Test auth (virtual users) is the local Development QA default.

    Available only in Development (never Canary/Production), on by default so
    the checked-out localhost build can drive persona/identity QA without an
    extra flag. An explicit ``NTA_ENABLE_TEST_AUTH=0`` still turns it off.
    """
    if not is_development():
        return False
    return str(os.environ.get("NTA_ENABLE_TEST_AUTH") or "1").strip().lower() not in {
        "0", "false", "no", "off",
    }


def impersonation_enabled() -> bool:
    """Owner impersonation ("open as persona") is the local Development QA default.

    Development-only (never Canary/Production), on by default so the owner can
    view the app as any persona on 127.0.0.1 without switching the server to
    staging. An explicit ``NTA_ENABLE_IMPERSONATION=0`` still turns it off.
    """
    if not is_development():
        return False
    flag = str(os.environ.get("NTA_ENABLE_IMPERSONATION") or "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def allow_real_payments() -> bool:
    if not is_production():
        return False
    return _compatible_bool(
        "STRATFORGE_REAL_PAYMENTS_ALLOWED", "NTA_ALLOW_REAL_PAYMENTS",
    )


def allow_live_orders() -> bool:
    if not is_production():
        return False
    return _compatible_bool(
        "STRATFORGE_LIVE_TRADING_ALLOWED", "NTA_ALLOW_LIVE_ORDERS",
    )


def rate_limits_disabled() -> bool:
    return is_development() and str(
        os.environ.get("NTA_DISABLE_RATE_LIMIT") or ""
    ).strip() == "1"


def _resolved_root(raw: str, project_root: Path) -> Path:
    path = Path(str(raw or "").strip()).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def _root_contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _first_value(names: Iterable[str]) -> str:
    for name in names:
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


@lru_cache(maxsize=128)
def _data_root_cached(
    base_text: str,
    environment: str,
    profile: str,
    production_raw: str,
    canary_raw: str,
    development_raw: str,
) -> Path:
    base = Path(base_text).resolve()
    # Preserve the historical library/import fallback. Real startup is still
    # fail-closed because strict Production requires STRATFORGE_DATA_ROOT.
    if environment == PRODUCTION and not production_raw:
        return (base / "data").resolve()
    production_default = base / ".stratforge-production-data-disabled"
    production_root = _resolved_root(
        production_raw or str(production_default),
        base,
    )
    canary_root = _resolved_root(
        canary_raw or str(base / ".stratforge-canary-data-disabled"), base,
    )
    legacy_default = base / "data" / "staging"
    development_default = (
        legacy_default if profile == STAGING else base / "data" / "development"
    )
    development_root = _resolved_root(
        development_raw or str(development_default), base,
    )
    roots = {
        DEVELOPMENT: development_root,
        CANARY: canary_root,
        PRODUCTION: production_root,
    }
    for left_name, left in roots.items():
        for right_name, right in roots.items():
            if left_name >= right_name:
                continue
            if (
                left == right
                or _root_contains(left, right)
                or _root_contains(right, left)
            ):
                raise RuntimeEnvError(
                    f"Data root {left_name} совпадает с {right_name} или вложен в него. "
                    "Задайте отдельные STRATFORGE_*_DATA_ROOT.",
                    503,
                )
    return roots[environment]


def data_root(project_root: Any = None) -> Path:
    """Return the isolated data directory for the selected environment.

    Root resolution performs Windows canonical-path syscalls and is used by
    every authenticated repository lookup.  Cache only by the complete set of
    environment/path inputs so tests and explicit profile switches remain
    isolated while steady-state requests avoid thousands of duplicate calls.
    """
    base = Path(project_root) if project_root is not None else _PROJECT_ROOT
    production_raw = _first_value(("STRATFORGE_DATA_ROOT", "NTA_DATA_ROOT"))
    canary_raw = _first_value(("STRATFORGE_CANARY_DATA_ROOT",))
    development_raw = _first_value((
        "STRATFORGE_DEVELOPMENT_DATA_ROOT", "NTA_STAGING_DATA_ROOT",
    ))
    return _data_root_cached(
        str(base), deployment_environment(), app_env(), production_raw,
        canary_raw, development_raw,
    )


def data_path(*parts: Any, project_root: Any = None) -> Path:
    path = data_root(project_root)
    for part in parts:
        path = path / str(part)
    return path


def allow_owner_telegram_mirror() -> bool:
    if is_development():
        return str(
            os.environ.get("NTA_STAGING_ALLOW_OWNER_TELEGRAM") or ""
        ).strip() == "1"
    return is_production()


def _safe_identifier(name: str, default: str, *, required: bool) -> str:
    configured = str(os.environ.get(name) or "").strip()
    if required and not configured:
        raise RuntimeEnvError(f"{name} обязателен в Canary/Production.", 503)
    value = configured or str(default or "").strip()
    if not value:
        return ""
    if not _ID_RE.fullmatch(value):
        raise RuntimeEnvError(
            f"{name} содержит недопустимые символы или слишком длинный.", 503,
        )
    return value


def _allowed_hosts(*, required: bool) -> Tuple[str, ...]:
    raw = str(os.environ.get("STRATFORGE_ALLOWED_HOSTS") or "").strip()
    if not raw:
        if required:
            raise RuntimeEnvError(
                "STRATFORGE_ALLOWED_HOSTS обязателен в Canary/Production.", 503,
            )
        return ("127.0.0.1", "localhost")
    hosts = []
    for item in raw.split(","):
        host = item.strip().lower().rstrip(".")
        if not host:
            continue
        if (
            "*" in host or "://" in host or "/" in host
            or host in {"0.0.0.0", "::"}
        ):
            raise RuntimeEnvError(
                f"Недопустимый host в STRATFORGE_ALLOWED_HOSTS: {host!r}.", 503,
            )
        if host not in hosts:
            hosts.append(host)
    if not hosts:
        raise RuntimeEnvError("STRATFORGE_ALLOWED_HOSTS пуст.", 503)
    if required and any(host in {"127.0.0.1", "localhost", "::1"} for host in hosts):
        raise RuntimeEnvError(
            "Canary/Production allowed-hosts не должен содержать localhost.", 503,
        )
    return tuple(hosts)


def _public_origin(*, required: bool, allowed_hosts: Tuple[str, ...]) -> str:
    raw = str(os.environ.get("STRATFORGE_PUBLIC_ORIGIN") or "").strip()
    if not raw:
        if required:
            raise RuntimeEnvError(
                "STRATFORGE_PUBLIC_ORIGIN обязателен в Canary/Production.", 503,
            )
        return "http://127.0.0.1"
    try:
        parsed = urllib.parse.urlsplit(raw)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise RuntimeEnvError(
            "STRATFORGE_PUBLIC_ORIGIN содержит некорректный URL.", 503,
        ) from exc
    hostname = str(parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise RuntimeEnvError(
            "STRATFORGE_PUBLIC_ORIGIN должен быть origin без path/query/credentials.",
            503,
        )
    if required and parsed.scheme != "https":
        raise RuntimeEnvError(
            "Canary/Production STRATFORGE_PUBLIC_ORIGIN должен использовать https.", 503,
        )
    if required and port not in {None, 443}:
        raise RuntimeEnvError(
            "Canary/Production public origin должен использовать стандартный TLS port 443.",
            503,
        )
    if hostname not in allowed_hosts:
        raise RuntimeEnvError(
            "Host STRATFORGE_PUBLIC_ORIGIN отсутствует в STRATFORGE_ALLOWED_HOSTS.",
            503,
        )
    if required and allowed_hosts != (hostname,):
        raise RuntimeEnvError(
            "Canary/Production принимает один canonical host, совпадающий с public origin.",
            503,
        )
    normalized_port = f":{port}" if port and port not in {80, 443} else ""
    return f"{parsed.scheme}://{hostname}{normalized_port}"


def _edge_mode(*, required: bool) -> str:
    raw = str(os.environ.get("STRATFORGE_EDGE_MODE") or "").strip().lower()
    if not raw:
        if required:
            raise RuntimeEnvError(
                "STRATFORGE_EDGE_MODE обязателен в Canary/Production.", 503,
            )
        return "direct-local"
    if raw not in _EDGE_MODES:
        raise RuntimeEnvError(
            "STRATFORGE_EDGE_MODE должен быть одним из: "
            + ", ".join(sorted(_EDGE_MODES)),
            503,
        )
    if required and raw == "direct-local":
        raise RuntimeEnvError(
            "Canary/Production не может использовать direct-local edge mode.", 503,
        )
    return raw


def _trusted_proxy_ips(*, required: bool) -> Tuple[str, ...]:
    raw = str(os.environ.get("STRATFORGE_TRUSTED_PROXY_IPS") or "").strip()
    if not raw:
        if required:
            raise RuntimeEnvError(
                "STRATFORGE_TRUSTED_PROXY_IPS обязателен в Canary/Production.", 503,
            )
        return ("127.0.0.1", "::1")
    values = []
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            normalized = str(ipaddress.ip_address(value))
        except ValueError as exc:
            raise RuntimeEnvError(
                "STRATFORGE_TRUSTED_PROXY_IPS принимает только точные IP, не CIDR.",
                503,
            ) from exc
        if normalized not in values:
            values.append(normalized)
    if not values:
        raise RuntimeEnvError("STRATFORGE_TRUSTED_PROXY_IPS пуст.", 503)
    return tuple(values)


def _positive_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = str(os.environ.get(name) or str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeEnvError(f"{name} должен быть целым числом.", 503) from exc
    if value < minimum or value > maximum:
        raise RuntimeEnvError(
            f"{name} должен быть в диапазоне {minimum}..{maximum}.", 503,
        )
    return value


def deployment_config(*, strict: bool = False) -> DeploymentConfig:
    environment = deployment_environment()
    remote_required = strict and environment in {CANARY, PRODUCTION}
    if remote_required:
        root_name = (
            "STRATFORGE_CANARY_DATA_ROOT"
            if environment == CANARY else "STRATFORGE_DATA_ROOT"
        )
        if not str(os.environ.get(root_name) or "").strip():
            raise RuntimeEnvError(
                f"{root_name} обязателен в {environment}.", 503,
            )
        for flag_name in (
            "STRATFORGE_LIVE_TRADING_ALLOWED",
            "STRATFORGE_REAL_PAYMENTS_ALLOWED",
        ):
            if _optional_bool(flag_name) is None:
                raise RuntimeEnvError(
                    f"{flag_name} должен быть задан явно в {environment}.", 503,
                )
    hostname = re.sub(r"[^A-Za-z0-9.-]+", "-", socket.gethostname()).strip("-")
    bind_host = str(
        os.environ.get("STRATFORGE_BIND_HOST")
        or ("127.0.0.1" if environment == DEVELOPMENT else "")
    ).strip()
    if remote_required and not bind_host:
        raise RuntimeEnvError(
            f"STRATFORGE_BIND_HOST обязателен в {environment}.", 503,
        )
    if bind_host in {"0.0.0.0", "::"} and _optional_bool(
        "STRATFORGE_PRIVATE_BIND_CONFIRMED"
    ) is not True:
        raise RuntimeEnvError(
            "Bind на все интерфейсы требует "
            "STRATFORGE_PRIVATE_BIND_CONFIRMED=1 и внешнего firewall/reverse proxy.",
            503,
        )

    allowed_hosts = _allowed_hosts(required=remote_required)
    (
        build_version, build_date, release_channel, release_status, build_id,
        git_commit_sha, artifact_sha256, build_timestamp_utc, dirty,
    ) = _release_identity(environment, required=remote_required)
    config = DeploymentConfig(
        environment=environment,
        runtime_profile=app_env(),
        environment_explicit=environment_explicit(),
        instance_id=_safe_identifier(
            "STRATFORGE_INSTANCE_ID",
            f"stratforge-dev-{hostname or 'local'}",
            required=remote_required,
        ),
        deployment_role=_safe_identifier(
            "STRATFORGE_DEPLOYMENT_ROLE",
            "all-in-one",
            required=remote_required,
        ),
        config_profile=_safe_identifier(
            "STRATFORGE_CONFIG_PROFILE",
            "local-development",
            required=remote_required,
        ),
        build_version=build_version,
        build_date=build_date,
        build_id=build_id,
        git_commit_sha=git_commit_sha,
        artifact_sha256=artifact_sha256,
        build_timestamp_utc=build_timestamp_utc,
        dirty=dirty,
        release_channel=release_channel,
        release_status=release_status,
        region=_safe_identifier(
            "STRATFORGE_REGION",
            "local",
            required=remote_required,
        ),
        bind_host=bind_host or "127.0.0.1",
        allowed_hosts=allowed_hosts,
        public_origin=_public_origin(
            required=remote_required, allowed_hosts=allowed_hosts,
        ),
        edge_mode=_edge_mode(required=remote_required),
        trusted_proxy_ips=_trusted_proxy_ips(required=remote_required),
        readiness_min_free_mb=_positive_int(
            "STRATFORGE_READINESS_MIN_FREE_MB",
            4096 if environment in {CANARY, PRODUCTION} else 128,
            minimum=1,
            maximum=1048576,
        ),
        api_max_inflight=_positive_int(
            "STRATFORGE_API_MAX_INFLIGHT", 48,
            minimum=1, maximum=1024,
        ),
        api_backlog=_positive_int(
            "STRATFORGE_API_BACKLOG",
            128 if environment in {CANARY, PRODUCTION} else 96,
            minimum=1, maximum=4096,
        ),
        api_max_body_bytes=_positive_int(
            "STRATFORGE_API_MAX_BODY_BYTES", 1048576,
            minimum=1024, maximum=8388608,
        ),
        worker_poll_ms=_positive_int(
            "STRATFORGE_WORKER_POLL_MS", 250,
            minimum=50, maximum=10000,
        ),
        worker_shutdown_grace_sec=_positive_int(
            "STRATFORGE_WORKER_SHUTDOWN_GRACE_SEC", 60,
            minimum=1, maximum=600,
        ),
        data_root=str(data_root()),
        database_id=_safe_identifier(
            "STRATFORGE_DATABASE_ID",
            "development-sqlite",
            required=remote_required,
        ),
        queue_id=_safe_identifier(
            "STRATFORGE_QUEUE_ID",
            "development-local-worker",
            required=remote_required,
        ),
        object_storage_id=_safe_identifier(
            "STRATFORGE_OBJECT_STORAGE_ID",
            "development-files",
            required=remote_required,
        ),
        telegram_bot_id=_safe_identifier(
            "STRATFORGE_TELEGRAM_BOT_ID",
            "development-disabled",
            required=remote_required,
        ),
        cookie_namespace=_safe_identifier(
            "STRATFORGE_COOKIE_NAMESPACE",
            "sf-dev",
            required=remote_required,
        ),
        signing_key_id=_safe_identifier(
            "STRATFORGE_SIGNING_KEY_ID",
            "development-local",
            required=remote_required,
        ),
        log_namespace=_safe_identifier(
            "STRATFORGE_LOG_NAMESPACE",
            "development",
            required=remote_required,
        ),
        live_trading_allowed=allow_live_orders(),
        real_payments_allowed=allow_real_payments(),
    )
    if config.deployment_role not in _PRODUCTION_ROLES:
        raise RuntimeEnvError(
            "STRATFORGE_DEPLOYMENT_ROLE должен быть одним из: "
            + ", ".join(sorted(_PRODUCTION_ROLES)),
            503,
        )
    if config.api_backlog < config.api_max_inflight:
        raise RuntimeEnvError(
            "STRATFORGE_API_BACKLOG не может быть меньше STRATFORGE_API_MAX_INFLIGHT.",
            503,
        )
    return config


def status() -> Dict[str, Any]:
    config = deployment_config(strict=False)
    return {
        **config.public_dict(),
        "app_env": app_env(),
        "deployment_environment": config.environment,
        "environment_explicit": config.environment_explicit,
        "is_development": is_development(),
        "is_canary": is_canary(),
        "is_staging": is_staging(),
        "is_production": is_production(),
        "test_auth_enabled": test_auth_enabled(),
        "impersonation_enabled": impersonation_enabled(),
        "allow_real_payments": allow_real_payments(),
        "allow_live_orders": allow_live_orders(),
        "rate_limits_disabled": rate_limits_disabled(),
        "allow_owner_telegram_mirror": allow_owner_telegram_mirror(),
        "data_root": str(data_root()),
        "deployment": config.as_dict(),
    }


def public_status() -> Dict[str, Any]:
    return deployment_config(strict=False).public_dict()


def assert_production_safe() -> None:
    """Retained name for the shared Canary/Production remote safety gate."""
    if not is_development():
        if str(os.environ.get("NTA_ENABLE_TEST_AUTH") or "").strip() == "1":
            raise RuntimeEnvError(
                "NTA_ENABLE_TEST_AUTH=1 запрещён в Canary/Production.", 503,
            )
        if str(os.environ.get("NTA_ENABLE_IMPERSONATION") or "").strip().lower() in {
            "1", "true", "yes", "on",
        }:
            raise RuntimeEnvError(
                "NTA_ENABLE_IMPERSONATION запрещён в Canary/Production.", 503,
            )
        if str(os.environ.get("NTA_DISABLE_RATE_LIMIT") or "").strip() == "1":
            raise RuntimeEnvError(
                "NTA_DISABLE_RATE_LIMIT=1 запрещён в Canary/Production.", 503,
            )
        return
    data_root()


def assert_startup_safe() -> DeploymentConfig:
    """Fail-closed validation used by the real backend entrypoint."""
    if not environment_explicit():
        raise RuntimeEnvError(
            "Окружение не задано. Установите DEPLOYMENT_ENV=development, "
            "DEPLOYMENT_ENV=canary или DEPLOYMENT_ENV=production.",
            503,
        )
    assert_production_safe()
    if not is_development() and str(
        os.environ.get("NTA_TEST_BYPASS_AUTH") or ""
    ).strip() == "1":
        raise RuntimeEnvError(
            "NTA_TEST_BYPASS_AUTH=1 запрещён в Canary/Production startup.", 503,
        )
    config = deployment_config(strict=True)
    assert_environment_isolation(config)
    return config


def require_staging(feature: str = "эта функция") -> None:
    if not is_development():
        raise RuntimeEnvError(
            f"{feature} доступна только в development/staging QA.",
            403,
        )


def require_test_auth() -> None:
    require_staging("Test auth")
    if not test_auth_enabled():
        raise RuntimeEnvError(
            "Test auth выключен. Установите NTA_ENABLE_TEST_AUTH=1 "
            "в development.",
            403,
        )


def require_impersonation() -> None:
    require_staging("Impersonation")
    if not impersonation_enabled():
        raise RuntimeEnvError(
            "Impersonation выключен (NTA_ENABLE_IMPERSONATION=0).",
            403,
        )


# --------------------------------------------------------------------------- #
# Phase 7: cross-environment isolation, namespaces and markers.
# --------------------------------------------------------------------------- #
# When a Canary process declares the Production reference identities it must
# never share, any collision fails startup closed. The references carry no
# secrets — only namespace/identity strings.
_PRODUCTION_REFERENCE_ENVS: Dict[str, str] = {
    "database_id": "STRATFORGE_PRODUCTION_DATABASE_ID",
    "queue_id": "STRATFORGE_PRODUCTION_QUEUE_ID",
    "object_storage_id": "STRATFORGE_PRODUCTION_OBJECT_STORAGE_ID",
    "telegram_bot_id": "STRATFORGE_PRODUCTION_TELEGRAM_BOT_ID",
    "cookie_namespace": "STRATFORGE_PRODUCTION_COOKIE_NAMESPACE",
    "signing_key_id": "STRATFORGE_PRODUCTION_SIGNING_KEY_ID",
    "log_namespace": "STRATFORGE_PRODUCTION_LOG_NAMESPACE",
    "instance_id": "STRATFORGE_PRODUCTION_INSTANCE_ID",
    "public_origin": "STRATFORGE_PRODUCTION_PUBLIC_ORIGIN",
}


def session_cookie_name() -> str:
    """Per-environment session cookie name (distinct for every environment).

    Development, Canary and Production each use a distinct cookie name so a
    session token minted for one contour can never be presented to, or accepted
    by, another — even when two contours share a registrable parent domain (for
    example ``canary.stratforges.com`` and ``stratforges.com``), where browser
    origin isolation alone would not scope a domain-wide cookie. See
    ``docs/adr/0008-environment-cookie-and-storage-isolation.md`` for the threat
    analysis. Distinct names apply only when the environment is *explicitly*
    selected (a real deployed Canary/Production always sets it explicitly); an
    implicit / unset environment — local development and the test suite — keeps
    the canonical ``sf_session`` name so existing local sessions and the test
    suite are unaffected. Production is not yet deployed, so naming it explicitly
    does not break any existing session migration.
    """
    if environment_explicit():
        env = deployment_environment()
        if env == CANARY:
            return "sf_canary_session"
        if env == PRODUCTION:
            return "sf_production_session"
    return "sf_session"


def local_storage_namespace() -> str:
    """Browser local-storage key prefix, distinct per environment.

    Defence in depth on top of browser per-origin storage isolation: each
    environment prefixes its persisted UI state so two contours never read each
    other's local-storage even inside the same browser or a shared parent
    domain. Distinct prefixes apply only when the environment is explicitly
    selected (a real deployed Canary/Production always sets it explicitly); an
    implicit / unset environment — local development and the test suite — keeps
    bare keys (unchanged).
    """
    if environment_explicit():
        env = deployment_environment()
        if env == CANARY:
            return CANARY
        if env == PRODUCTION:
            return PRODUCTION
    return ""


def telegram_environment_marker() -> str:
    """Prefix for outgoing Telegram messages. Production is unmarked."""
    env = deployment_environment()
    if env == CANARY:
        return "[CANARY] "
    if env == DEVELOPMENT:
        return "[DEV] "
    return ""


def _reference_collision(field: str, current: str, env_name: str) -> None:
    reference = str(os.environ.get(env_name) or "").strip()
    if reference and current and reference.casefold() == current.casefold():
        raise RuntimeEnvError(
            f"Canary {field} совпадает с Production ({env_name}); "
            "окружения обязаны быть полностью изолированы.",
            503,
        )


def assert_environment_isolation(config: Optional[DeploymentConfig] = None) -> None:
    """Fail-closed guard that Canary never overlaps with Production.

    Rejects a shared database DSN/id, queue/storage/telegram/cookie/signing/log
    namespace, instance id, public origin or data root. References carry no
    secrets. A no-op outside Canary except a symmetric Production guard.
    """
    config = config or deployment_config(strict=False)
    env = config.environment
    if env == PRODUCTION:
        # A Production process must never carry a declared Canary identity.
        canary_bot = str(os.environ.get("STRATFORGE_CANARY_TELEGRAM_BOT_ID") or "").strip()
        if canary_bot and config.telegram_bot_id and canary_bot.casefold() == config.telegram_bot_id.casefold():
            raise RuntimeEnvError(
                "Production telegram_bot_id совпадает с Canary; окружения должны быть изолированы.",
                503,
            )
        return
    if env != CANARY:
        return
    for field, env_name in _PRODUCTION_REFERENCE_ENVS.items():
        _reference_collision(field, str(getattr(config, field, "") or "").strip(), env_name)
    canary_dsn = str(os.environ.get("STRATFORGE_DATABASE_URL") or "").strip()
    prod_dsn = str(os.environ.get("STRATFORGE_PRODUCTION_DATABASE_URL") or "").strip()
    if canary_dsn and prod_dsn and canary_dsn.casefold() == prod_dsn.casefold():
        raise RuntimeEnvError(
            "Canary STRATFORGE_DATABASE_URL совпадает с Production; отдельная база обязательна.",
            503,
        )
    prod_root = str(os.environ.get("STRATFORGE_PRODUCTION_DATA_ROOT") or "").strip()
    if prod_root:
        try:
            same = Path(config.data_root).resolve() == Path(prod_root).resolve()
        except (OSError, ValueError):
            same = str(config.data_root).strip().casefold() == prod_root.casefold()
        if same:
            raise RuntimeEnvError(
                "Canary data root совпадает с Production data root.", 503,
            )
    prod_hosts = {
        host.strip().casefold()
        for host in str(os.environ.get("STRATFORGE_PRODUCTION_ALLOWED_HOSTS") or "").split(",")
        if host.strip()
    }
    if prod_hosts and any(host.casefold() in prod_hosts for host in config.allowed_hosts):
        raise RuntimeEnvError(
            "Canary allowed-hosts пересекается с Production allowed-hosts.", 503,
        )
