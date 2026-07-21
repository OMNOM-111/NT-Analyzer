"""Typed StratForge deployment environment and startup safety gates.

There are two deployable environments:

development
    Private Windows development. Local SQLite/JSON/DPAPI and test-only
    features may be enabled explicitly.

production
    The central multi-user service. Startup is fail-closed and requires
    explicit resource identities.

The historical staging value remains accepted as a compatibility QA profile,
but maps to the development deployment boundary and is not a third deployment
target.

Library calls retain the historical production fallback so imports and older
tests remain compatible. The real server entrypoint must call
assert_startup_safe(), which rejects an implicit environment.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import ipaddress
import os
from pathlib import Path
import re
import socket
from typing import Any, Dict, Iterable, Optional, Tuple
import urllib.parse


DEVELOPMENT = "development"
PRODUCTION = "production"
STAGING = "staging"  # Legacy isolated-QA profile; deploys as DEVELOPMENT.
_VALID = {DEVELOPMENT, PRODUCTION, STAGING}
_ENV_KEYS = ("STRATFORGE_ENV", "NTA_APP_ENV", "NTA_ENV")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
_PRODUCTION_ROLES = {
    "all-in-one", "api", "worker", "telegram", "connector-control",
}
_EDGE_MODES = {"direct-local", "cloudflare-tunnel", "reverse-proxy"}


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
    region: str
    bind_host: str
    allowed_hosts: Tuple[str, ...]
    public_origin: str
    edge_mode: str
    trusted_proxy_ips: Tuple[str, ...]
    readiness_min_free_mb: int
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
        return asdict(self)

    def public_dict(self) -> Dict[str, Any]:
        return {
            "environment": self.environment,
            "runtime_profile": self.runtime_profile,
            "instance_id": self.instance_id,
            "deployment_role": self.deployment_role,
            "config_profile": self.config_profile,
            "build_version": self.build_version,
            "region": self.region,
            "public_origin": self.public_origin,
            "live_trading_allowed": self.live_trading_allowed,
            "real_payments_allowed": self.real_payments_allowed,
        }


def _normalize_env(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in ("prod", "live"):
        return PRODUCTION
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
        PRODUCTION if value == PRODUCTION else DEVELOPMENT
        for _, value in values
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
    two-environment boundary.
    """
    values = _configured_environments()
    if not values:
        return PRODUCTION
    priority = {key: index for index, key in enumerate(_ENV_KEYS)}
    return min(values, key=lambda item: priority[item[0]])[1]


def deployment_environment() -> str:
    return PRODUCTION if app_env() == PRODUCTION else DEVELOPMENT


def is_development() -> bool:
    return deployment_environment() == DEVELOPMENT


def is_staging() -> bool:
    """Compatibility name for the isolated non-production boundary."""
    return is_development()


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
    """Test auth may run only in development with explicit opt-in."""
    if not is_development():
        return False
    return str(os.environ.get("NTA_ENABLE_TEST_AUTH") or "").strip() == "1"


def impersonation_enabled() -> bool:
    """Owner impersonation is development-only."""
    if not is_development():
        return False
    # Preserve the historical staging default while new development starts
    # fail-closed unless it opts in.
    default = "1" if app_env() == STAGING else "0"
    flag = str(os.environ.get("NTA_ENABLE_IMPERSONATION") or default).strip().lower()
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


def _first_value(names: Iterable[str]) -> str:
    for name in names:
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def data_root(project_root: Any = None) -> Path:
    """Return the isolated data directory for the selected environment."""
    base = Path(project_root or Path(__file__).resolve().parent.parent).resolve()
    production_root = _resolved_root(
        _first_value(("STRATFORGE_DATA_ROOT", "NTA_DATA_ROOT"))
        or str(base / "data"),
        base,
    )
    if is_production():
        return production_root

    development_raw = _first_value((
        "STRATFORGE_DEVELOPMENT_DATA_ROOT", "NTA_STAGING_DATA_ROOT",
    ))
    legacy_default = base / "data" / "staging"
    development_default = (
        legacy_default if app_env() == STAGING else base / "data" / "development"
    )
    development_root = _resolved_root(
        development_raw or str(development_default), base,
    )
    if development_root == production_root:
        raise RuntimeEnvError(
            "Development data root совпадает с production data root. "
            "Задайте отдельный STRATFORGE_DEVELOPMENT_DATA_ROOT.",
            503,
        )
    return development_root


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
    return True


def _safe_identifier(name: str, default: str, *, required: bool) -> str:
    configured = str(os.environ.get(name) or "").strip()
    if required and not configured:
        raise RuntimeEnvError(f"{name} обязателен в production.", 503)
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
                "STRATFORGE_ALLOWED_HOSTS обязателен в production.", 503,
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
            "Production allowed-hosts не должен содержать localhost.", 503,
        )
    return tuple(hosts)


def _public_origin(*, required: bool, allowed_hosts: Tuple[str, ...]) -> str:
    raw = str(os.environ.get("STRATFORGE_PUBLIC_ORIGIN") or "").strip()
    if not raw:
        if required:
            raise RuntimeEnvError(
                "STRATFORGE_PUBLIC_ORIGIN обязателен в production.", 503,
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
            "Production STRATFORGE_PUBLIC_ORIGIN должен использовать https.", 503,
        )
    if required and port not in {None, 443}:
        raise RuntimeEnvError(
            "Production public origin должен использовать стандартный TLS port 443.",
            503,
        )
    if hostname not in allowed_hosts:
        raise RuntimeEnvError(
            "Host STRATFORGE_PUBLIC_ORIGIN отсутствует в STRATFORGE_ALLOWED_HOSTS.",
            503,
        )
    if required and allowed_hosts != (hostname,):
        raise RuntimeEnvError(
            "Production принимает только один canonical host, совпадающий с public origin.",
            503,
        )
    normalized_port = f":{port}" if port and port not in {80, 443} else ""
    return f"{parsed.scheme}://{hostname}{normalized_port}"


def _edge_mode(*, required: bool) -> str:
    raw = str(os.environ.get("STRATFORGE_EDGE_MODE") or "").strip().lower()
    if not raw:
        if required:
            raise RuntimeEnvError("STRATFORGE_EDGE_MODE обязателен в production.", 503)
        return "direct-local"
    if raw not in _EDGE_MODES:
        raise RuntimeEnvError(
            "STRATFORGE_EDGE_MODE должен быть одним из: "
            + ", ".join(sorted(_EDGE_MODES)),
            503,
        )
    if required and raw == "direct-local":
        raise RuntimeEnvError(
            "Production не может использовать direct-local edge mode.", 503,
        )
    return raw


def _trusted_proxy_ips(*, required: bool) -> Tuple[str, ...]:
    raw = str(os.environ.get("STRATFORGE_TRUSTED_PROXY_IPS") or "").strip()
    if not raw:
        if required:
            raise RuntimeEnvError(
                "STRATFORGE_TRUSTED_PROXY_IPS обязателен в production.", 503,
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
    production_required = strict and environment == PRODUCTION
    if production_required:
        if not str(os.environ.get("STRATFORGE_DATA_ROOT") or "").strip():
            raise RuntimeEnvError(
                "STRATFORGE_DATA_ROOT обязателен в production.", 503,
            )
        for flag_name in (
            "STRATFORGE_LIVE_TRADING_ALLOWED",
            "STRATFORGE_REAL_PAYMENTS_ALLOWED",
        ):
            if _optional_bool(flag_name) is None:
                raise RuntimeEnvError(
                    f"{flag_name} должен быть задан явно в production.", 503,
                )
    hostname = re.sub(r"[^A-Za-z0-9.-]+", "-", socket.gethostname()).strip("-")
    bind_host = str(
        os.environ.get("STRATFORGE_BIND_HOST")
        or ("127.0.0.1" if environment == DEVELOPMENT else "")
    ).strip()
    if production_required and not bind_host:
        raise RuntimeEnvError("STRATFORGE_BIND_HOST обязателен в production.", 503)
    if bind_host in {"0.0.0.0", "::"} and _optional_bool(
        "STRATFORGE_PRIVATE_BIND_CONFIRMED"
    ) is not True:
        raise RuntimeEnvError(
            "Bind на все интерфейсы требует "
            "STRATFORGE_PRIVATE_BIND_CONFIRMED=1 и внешнего firewall/reverse proxy.",
            503,
        )

    allowed_hosts = _allowed_hosts(required=production_required)
    config = DeploymentConfig(
        environment=environment,
        runtime_profile=app_env(),
        environment_explicit=environment_explicit(),
        instance_id=_safe_identifier(
            "STRATFORGE_INSTANCE_ID",
            f"stratforge-dev-{hostname or 'local'}",
            required=production_required,
        ),
        deployment_role=_safe_identifier(
            "STRATFORGE_DEPLOYMENT_ROLE",
            "all-in-one",
            required=production_required,
        ),
        config_profile=_safe_identifier(
            "STRATFORGE_CONFIG_PROFILE",
            "local-development",
            required=production_required,
        ),
        build_version=_safe_identifier(
            "STRATFORGE_BUILD_VERSION",
            "development",
            required=production_required,
        ),
        region=_safe_identifier(
            "STRATFORGE_REGION",
            "local",
            required=production_required,
        ),
        bind_host=bind_host or "127.0.0.1",
        allowed_hosts=allowed_hosts,
        public_origin=_public_origin(
            required=production_required, allowed_hosts=allowed_hosts,
        ),
        edge_mode=_edge_mode(required=production_required),
        trusted_proxy_ips=_trusted_proxy_ips(required=production_required),
        readiness_min_free_mb=_positive_int(
            "STRATFORGE_READINESS_MIN_FREE_MB",
            4096 if environment == PRODUCTION else 128,
            minimum=1,
            maximum=1048576,
        ),
        data_root=str(data_root()),
        database_id=_safe_identifier(
            "STRATFORGE_DATABASE_ID",
            "development-sqlite",
            required=production_required,
        ),
        queue_id=_safe_identifier(
            "STRATFORGE_QUEUE_ID",
            "development-local-worker",
            required=production_required,
        ),
        object_storage_id=_safe_identifier(
            "STRATFORGE_OBJECT_STORAGE_ID",
            "development-files",
            required=production_required,
        ),
        telegram_bot_id=_safe_identifier(
            "STRATFORGE_TELEGRAM_BOT_ID",
            "development-disabled",
            required=production_required,
        ),
        cookie_namespace=_safe_identifier(
            "STRATFORGE_COOKIE_NAMESPACE",
            "sf-dev",
            required=production_required,
        ),
        signing_key_id=_safe_identifier(
            "STRATFORGE_SIGNING_KEY_ID",
            "development-local",
            required=production_required,
        ),
        log_namespace=_safe_identifier(
            "STRATFORGE_LOG_NAMESPACE",
            "development",
            required=production_required,
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
    return config


def status() -> Dict[str, Any]:
    config = deployment_config(strict=False)
    return {
        "app_env": app_env(),
        "deployment_environment": config.environment,
        "environment_explicit": config.environment_explicit,
        "is_development": is_development(),
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
    """Retained compatibility gate for tests and library callers."""
    if is_production():
        if str(os.environ.get("NTA_ENABLE_TEST_AUTH") or "").strip() == "1":
            raise RuntimeEnvError(
                "NTA_ENABLE_TEST_AUTH=1 запрещён в production.", 503,
            )
        if str(os.environ.get("NTA_ENABLE_IMPERSONATION") or "").strip().lower() in {
            "1", "true", "yes", "on",
        }:
            raise RuntimeEnvError(
                "NTA_ENABLE_IMPERSONATION запрещён в production.", 503,
            )
        if str(os.environ.get("NTA_DISABLE_RATE_LIMIT") or "").strip() == "1":
            raise RuntimeEnvError(
                "NTA_DISABLE_RATE_LIMIT=1 запрещён в production.", 503,
            )
        return
    data_root()


def assert_startup_safe() -> DeploymentConfig:
    """Fail-closed validation used by the real backend entrypoint."""
    if not environment_explicit():
        raise RuntimeEnvError(
            "Окружение не задано. Установите STRATFORGE_ENV=development "
            "или STRATFORGE_ENV=production.",
            503,
        )
    assert_production_safe()
    if is_production() and str(
        os.environ.get("NTA_TEST_BYPASS_AUTH") or ""
    ).strip() == "1":
        raise RuntimeEnvError(
            "NTA_TEST_BYPASS_AUTH=1 запрещён в production startup.", 503,
        )
    return deployment_config(strict=True)


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
