"""Load local secrets from data/integrations/secrets.local.json (gitignored).

Only sets environment variables that are not already set in the process.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


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
