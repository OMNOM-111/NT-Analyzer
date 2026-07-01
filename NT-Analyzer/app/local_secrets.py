"""Load local secrets from data/integrations/secrets.local.json (gitignored).

Only sets environment variables that are not already set in the process.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict


_LOCK = threading.RLock()


def secrets_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "integrations" / "secrets.local.json"


def apply() -> bool:
    path = secrets_path()
    if not path.is_file():
        return False
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    if not isinstance(doc, dict):
        return False
    for key, value in doc.items():
        name = str(key).strip()
        if not name or name in os.environ:
            continue
        text = str(value).strip() if value is not None else ""
        if text:
            os.environ[name] = text
    return True


def read() -> Dict[str, str]:
    """Read the local secret store without exposing it through an API."""
    path = secrets_path()
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in doc.items()
        if str(key).strip() and value is not None and str(value).strip()
    }


def update(values: Dict[str, Any]) -> bool:
    """Atomically update local secrets and the current process environment.

    ``None`` or an empty string removes a key. Secret values are never returned.
    """
    with _LOCK:
        doc: Dict[str, str] = read()
        for raw_key, raw_value in values.items():
            key = str(raw_key or "").strip()
            if not key:
                continue
            value = "" if raw_value is None else str(raw_value).strip()
            if value:
                doc[key] = value
                os.environ[key] = value
            else:
                doc.pop(key, None)
                os.environ.pop(key, None)

        path = secrets_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(
                json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return False
        return True
