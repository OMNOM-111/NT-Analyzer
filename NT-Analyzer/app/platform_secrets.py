"""Platform secrets: the credentials the deployment itself owns.

StratForge handles three kinds of credential and they must not be confused,
because the rules for each are different:

* **platform secrets** -- owner/system credentials the deployment holds on its
  own behalf: the Google client secret, the Resend API key, signing material.
  This module is the only sanctioned home for them.
* **user/workspace BYOK secrets** -- an AI provider key a person brings.
  Those belong to that person's workspace, are encrypted at rest and are never
  returned to any client. They do not live here.
* **non-secret configuration** -- ports, origins, feature flags. Ordinary
  config files, in the repository, no special handling.

What this module guarantees for the first kind:

Values live outside the repository, in one external directory, in a separate
file per environment, so Canary and Production can never read each other's.
The directory is refused outright if it sits inside the checkout -- that is
the mistake this exists to prevent. On POSIX a group- or world-readable file
is refused as well.

A missing required secret fails closed: the caller gets an error naming the
variable and the environment, never a silent empty string that turns into a
half-working integration.

Replacement is atomic and keeps exactly one previous copy, so a bad value can
be rolled back without going back to the provider. The audit records the
secret's name, its environment, when it changed and who changed it -- never
the value, not even masked, not even partially.

Nothing here ever returns a plaintext value to an API, a log line, an
exception message, a health endpoint or a support bundle. `redact()` exists so
that anything which might carry a value can be scrubbed before it is written
anywhere.
"""
from __future__ import annotations

import os
import re
import stat
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from . import runtime_env


class PlatformSecretError(RuntimeError):
    """Safe to show. Never carries a secret value."""


class PlatformSecretMissing(PlatformSecretError):
    """A required secret is not configured for this environment."""


_LOCK = threading.RLock()

ENVIRONMENTS = ("development", "canary", "production")

#: The platform secrets this deployment knows about. A name absent from here
#: cannot be read or written through this module: an unknown name is far more
#: likely to be a typo that silently reads nothing than a new credential.
KNOWN_SECRETS: Dict[str, str] = {
    "NTA_GOOGLE_CLIENT_SECRET": "Google OAuth client secret",
    "NTA_GOOGLE_CLIENT_ID": "Google OAuth client id",
    "NTA_RESEND_API_KEY": "Resend API key for transactional e-mail",
    "NTA_TELEGRAM_BOT_TOKEN": "Telegram bot token",
    "STRATFORGE_OWNER_MARKET_GATEWAY_TOKEN": "Owner market-data gateway token",
    "STRATFORGE_CONNECTOR_RELEASE_SIGNING_KEY": "Connector release signing key",
}

#: Secrets without which the environment must not pretend to work.
REQUIRED_BY_ENVIRONMENT: Dict[str, tuple] = {
    "development": (),
    "canary": ("NTA_GOOGLE_CLIENT_SECRET", "NTA_RESEND_API_KEY"),
    "production": ("NTA_GOOGLE_CLIENT_SECRET", "NTA_RESEND_API_KEY"),
}

_DIR_ENV = "STRATFORGE_SECRETS_DIR"
_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,80}$")
_LINE_RE = re.compile(r"^([A-Z][A-Z0-9_]{2,80})=(.*)$")

# Anything shorter is not worth redacting and would turn ordinary text into
# a wall of asterisks.
_MIN_REDACTABLE = 8


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def directory() -> Path:
    """Where platform secrets live. Never inside the repository.

    An operator who points this at the checkout would put live credentials one
    ``git add -A`` away from being published, so that is refused rather than
    warned about.
    """
    raw = str(os.environ.get(_DIR_ENV) or "").strip()
    if raw:
        path = Path(os.path.expandvars(os.path.expanduser(raw))).resolve()
    elif os.name == "nt":
        base = os.environ.get("PROGRAMDATA") or r"C:\ProgramData"
        path = Path(base).resolve() / "StratForge" / "secrets"
    else:
        path = Path("/etc/stratforge/secrets")

    repo = _repo_root()
    try:
        path.relative_to(repo)
    except ValueError:
        return path
    raise PlatformSecretError(
        f"Каталог секретов {path} находится внутри репозитория. "
        "Платформенные секреты не хранятся в Git; укажите внешний путь "
        f"в {_DIR_ENV}."
    )


def _environment() -> str:
    env = str(runtime_env.deployment_environment() or "").strip().lower()
    return env if env in ENVIRONMENTS else "development"


def path_for(environment: str = "") -> Path:
    env = str(environment or _environment()).strip().lower()
    if env not in ENVIRONMENTS:
        raise PlatformSecretError(f"Неизвестное окружение: {env}")
    return directory() / f"{env}.env"


def _check_permissions(path: Path) -> None:
    """Refuse a secret file the whole machine can read.

    Windows has no equivalent bit to check here; its access control lives in
    ACLs, which this deliberately does not try to interpret.
    """
    if os.name == "nt":
        return
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & (stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWOTH):
        raise PlatformSecretError(
            f"Файл секретов {path} доступен группе или всем "
            f"({stat.filemode(mode)}). Ожидается 0600."
        )


def _parse(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE_RE.match(line)
        if not match:
            continue
        name, value = match.group(1), match.group(2).strip()
        if value and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if value:
            out[name] = value
    return out


def _read_file(environment: str = "") -> Dict[str, str]:
    path = path_for(environment)
    if not path.is_file():
        return {}
    _check_permissions(path)
    try:
        return _parse(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise PlatformSecretError(
            f"Не удалось прочитать секреты окружения: {type(exc).__name__}"
        ) from None


def _write_file(values: Mapping[str, str], environment: str = "") -> None:
    """Replace the environment's file atomically, keeping one previous copy."""
    path = path_for(environment)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "# StratForge platform secrets. Values only; never commit this file.",
        f"# environment: {environment or _environment()}",
        "",
    ]
    for name in sorted(values):
        body.append(f"{name}={values[name]}")
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("\n".join(body) + "\n", encoding="utf-8")
    if os.name != "nt":
        os.chmod(temporary, 0o600)
    if path.is_file():
        backup = path.with_name(path.name + ".previous")
        try:
            backup.unlink()
        except FileNotFoundError:
            pass
        os.replace(path, backup)
        if os.name != "nt":
            try:
                os.chmod(backup, 0o600)
            except OSError:
                pass
    os.replace(temporary, path)


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #
def get(name: str, environment: str = "") -> str:
    """The value, or an empty string. Prefer :func:`require` for anything the
    deployment cannot work without."""
    name = str(name or "").strip()
    if name not in KNOWN_SECRETS:
        raise PlatformSecretError(f"Неизвестный платформенный секрет: {name[:80]}")
    with _LOCK:
        value = _read_file(environment).get(name, "")
    # An operator-set process variable still wins, so an emergency override
    # does not require editing files on a live host.
    return str(os.environ.get(name) or value or "")


def require(name: str, environment: str = "") -> str:
    """The value, or a refusal naming what is missing and where.

    Fail closed. A missing credential that reads as an empty string produces an
    integration that looks configured and silently does nothing.
    """
    value = get(name, environment)
    if not value:
        env = environment or _environment()
        raise PlatformSecretMissing(
            f"Платформенный секрет {name} не задан для окружения {env}."
        )
    return value


def missing_required(environment: str = "") -> List[str]:
    env = str(environment or _environment()).strip().lower()
    absent = []
    for name in REQUIRED_BY_ENVIRONMENT.get(env, ()):
        try:
            if not get(name, env):
                absent.append(name)
        except PlatformSecretError:
            absent.append(name)
    return absent


# --------------------------------------------------------------------------- #
# Status, never values
# --------------------------------------------------------------------------- #
def status(environment: str = "") -> Dict[str, Any]:
    """What the owner surface renders. Carries no value and no fragment of one."""
    env = str(environment or _environment()).strip().lower()
    try:
        present = _read_file(env)
        readable = True
        detail = ""
    except PlatformSecretError as exc:
        present, readable, detail = {}, False, str(exc)
    changes = {row["name"]: row for row in _audit_rows(env)}
    rows = []
    for name, description in sorted(KNOWN_SECRETS.items()):
        configured = bool(os.environ.get(name) or present.get(name))
        rows.append({
            "name": name,
            "description": description,
            "environment": env,
            "configured": configured,
            "required": name in REQUIRED_BY_ENVIRONMENT.get(env, ()),
            "last_rotated_at_utc": str(
                (changes.get(name) or {}).get("changed_at_utc") or ""),
            "last_rotated_by": str((changes.get(name) or {}).get("actor") or ""),
        })
    return {
        "environment": env,
        "store_readable": readable,
        "store_detail": detail,
        "missing_required": missing_required(env),
        "secrets": rows,
    }


# --------------------------------------------------------------------------- #
# Audit: name, environment, when, who. Never the value.
# --------------------------------------------------------------------------- #
def _audit_path() -> Path:
    return directory() / "rotation-audit.log"


def _audit_rows(environment: str = "") -> List[Dict[str, str]]:
    import json

    path = _audit_path()
    if not path.is_file():
        return []
    env = str(environment or "").strip().lower()
    rows: List[Dict[str, str]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and (not env or row.get("environment") == env):
                rows.append(row)
    except OSError:
        return []
    return rows


def _audit(name: str, environment: str, actor: str, action: str) -> None:
    import json

    path = _audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "schema_version": 1,
        "name": str(name)[:80],
        "environment": str(environment)[:20],
        "action": str(action)[:20],
        "changed_at_utc": _now(),
        "actor": str(actor or "")[:80],
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def audit(environment: str = "", limit: int = 200) -> List[Dict[str, str]]:
    rows = _audit_rows(environment)
    return rows[-max(1, min(int(limit or 200), 1000)):]


# --------------------------------------------------------------------------- #
# Replacement
# --------------------------------------------------------------------------- #
def replace(name: str, value: str, *, actor: str, environment: str = "") -> Dict[str, Any]:
    """Put a new value in place atomically, keeping the previous one.

    Returns status only. The value never travels back out of this function.
    """
    name = str(name or "").strip()
    if name not in KNOWN_SECRETS:
        raise PlatformSecretError(f"Неизвестный платформенный секрет: {name[:80]}")
    if not _NAME_RE.match(name):
        raise PlatformSecretError("Недопустимое имя секрета.")
    text = str(value or "").strip()
    if not text:
        raise PlatformSecretError(
            f"Пустое значение для {name}: замена отклонена. "
            "Для удаления используйте отдельную операцию."
        )
    if "\n" in text or "\r" in text:
        raise PlatformSecretError("Значение секрета не может содержать перевод строки.")
    env = str(environment or _environment()).strip().lower()
    with _LOCK:
        values = dict(_read_file(env))
        values[name] = text
        _write_file(values, env)
        _audit(name, env, actor, "replace")
    return {"ok": True, "name": name, "environment": env,
            "changed_at_utc": _now()}


def rollback(name: str, *, actor: str, environment: str = "") -> Dict[str, Any]:
    """Restore the previous file. The escape hatch for a bad value."""
    name = str(name or "").strip()
    env = str(environment or _environment()).strip().lower()
    path = path_for(env)
    backup = path.with_name(path.name + ".previous")
    if not backup.is_file():
        raise PlatformSecretError("Предыдущая версия файла секретов отсутствует.")
    with _LOCK:
        _check_permissions(backup)
        current = path.read_bytes() if path.is_file() else b""
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(backup.read_bytes())
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        if current:
            backup.write_bytes(current)
        _audit(name or "(file)", env, actor, "rollback")
    return {"ok": True, "environment": env, "rolled_back_at_utc": _now()}


# --------------------------------------------------------------------------- #
# Redaction
# --------------------------------------------------------------------------- #
def live_values() -> List[str]:
    """Every platform secret value currently configured, for scrubbing only."""
    values = []
    for env in ENVIRONMENTS:
        try:
            values.extend(_read_file(env).values())
        except PlatformSecretError:
            continue
    for name in KNOWN_SECRETS:
        current = str(os.environ.get(name) or "")
        if current:
            values.append(current)
    return [v for v in values if len(v) >= _MIN_REDACTABLE]


def redact(text: Any) -> Any:
    """Replace any configured platform secret with a marker.

    The last line of defence for anything that might reach a log, an exception,
    a support bundle or a config dump. It is deliberately value-based: a field
    name allow-list cannot catch a secret that was interpolated into a message.
    """
    if not isinstance(text, str) or not text:
        return text
    out = text
    for value in live_values():
        if value and value in out:
            out = out.replace(value, "***redacted***")
    return out
