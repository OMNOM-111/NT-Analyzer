"""User research folder ingestion.

Tracks per-file mtime+sha so AI can detect which files are new or changed
relative to the last cycle. Spec requires AI to never ignore new user files.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from . import paths
from .io_utils import read_json, write_json_atomic

_TEXT_EXTS = {".md", ".markdown", ".txt", ".csv", ".json", ".jsonl", ".yaml", ".yml"}


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def scan() -> Dict[str, Any]:
    """Scan user_research folder, return a manifest of files.

    Result: {
        "scanned_at_utc": ISO,
        "files": [{rel_path, size, mtime, sha256, ext, kind}, ...],
        "new": [rel_path...],
        "changed": [rel_path...],
        "removed": [rel_path...],
    }
    """
    paths.ensure_dirs()
    root = paths.USER_RESEARCH_DIR
    state_path = paths.REGISTRY_DIR / "user_research_state.json"
    prior = read_json(state_path, default={"files": {}}) or {"files": {}}
    prior_files = prior.get("files", {})

    current: Dict[str, Dict[str, Any]] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel == "README.md":
            continue
        try:
            stat = p.stat()
        except OSError:
            continue
        sha = _hash_file(p)
        current[rel] = {
            "rel_path": rel,
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
            "sha256": sha,
            "ext": p.suffix.lower(),
            "kind": _classify(rel),
        }

    new: List[str] = []
    changed: List[str] = []
    for rel, meta in current.items():
        prev = prior_files.get(rel)
        if not prev:
            new.append(rel)
        elif prev.get("sha256") != meta["sha256"]:
            changed.append(rel)
    removed = [r for r in prior_files.keys() if r not in current]

    state = {
        "scanned_at_utc": _now(),
        "files": current,
    }
    write_json_atomic(state_path, state)

    return {
        "scanned_at_utc": state["scanned_at_utc"],
        "files": list(current.values()),
        "new": new,
        "changed": changed,
        "removed": removed,
    }


def _classify(rel_path: str) -> str:
    rp = rel_path.lower()
    if rp.startswith("postmortems/"):
        return "postmortem"
    if rp.startswith("curated/"):
        return "curated"
    if rp.startswith("incoming/"):
        return "incoming"
    return "loose"


def read_file(rel_path: str, max_bytes: int = 200_000) -> Tuple[str, Dict[str, Any]]:
    """Read a user_research file as text with size guard.

    Returns (text, meta). Binary or oversize files are returned with empty text
    and a flag in meta.
    """
    p = paths.USER_RESEARCH_DIR / rel_path
    if not p.exists() or not p.is_file():
        return "", {"exists": False}
    size = p.stat().st_size
    meta = {"exists": True, "size": size, "truncated": False}
    if p.suffix.lower() not in _TEXT_EXTS:
        meta["binary"] = True
        return "", meta
    if size > max_bytes:
        with p.open("r", encoding="utf-8", errors="replace") as f:
            text = f.read(max_bytes)
        meta["truncated"] = True
        return text, meta
    with p.open("r", encoding="utf-8", errors="replace") as f:
        return f.read(), meta


def all_files() -> List[Dict[str, Any]]:
    state_path = paths.REGISTRY_DIR / "user_research_state.json"
    state = read_json(state_path, default={"files": {}}) or {"files": {}}
    return list(state.get("files", {}).values())
