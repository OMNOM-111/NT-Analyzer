"""The old «AI агенты» registry, frozen as a read-only archive.

The archive exists so the owner can still see how the old system was arranged,
check the old model/role assignments, read the historical statistics and
investigate any disagreement after the migration. It is a *copy*: the live
files are never moved, edited or deleted by anything here.

The archive is inert. Nothing in the running system - the router, the
coordinator, the ratings of current assignments, task execution - reads this
module; only the migration and the Legacy view do. A test pins that.

Secrets never enter it: API keys live in the protected secret store, not in
these files, and `freeze()` refuses a source that looks like it carries one.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .. import runtime_env

# What "the old registry" is, as one closed list: the agents themselves, the
# usage log that records what they did and what it cost, the star ratings and
# the two standing agent configurations.
SOURCES = (
    ("registry", ("integrations", "ai_agents.registry.json"), "file"),
    ("usage", ("ai_lab", "registry", "agent_usage"), "dir"),
    ("ratings", ("ai_lab", "registry", "star_ratings.json"), "file"),
    ("chief_agent", ("ai_lab", "registry", "chief_agent.json"), "file"),
    ("news_agent", ("ai_lab", "registry", "news_agent.json"), "file"),
)

SECRET_KEYS = re.compile(r"(api[_-]?key|secret|password|bearer|access[_-]?token|refresh[_-]?token)", re.I)
SECRET_VALUES = re.compile(r"\b(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})")


class ArchiveError(RuntimeError):
    """The archive could not be written, or no longer matches its manifest."""


def archive_root(project_root=None) -> Path:
    return runtime_env.data_path("legacy_archive", "ai_agents", project_root=project_root)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _records(path: Path) -> int:
    """How many records a source holds, so the reconciliation can count them."""
    if path.suffix == ".jsonl":
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if isinstance(value, dict) and isinstance(value.get("agents"), list):
        return len(value["agents"])
    return len(value) if isinstance(value, (list, dict)) else 1


def _refuse_secrets(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    if SECRET_VALUES.search(text):
        raise ArchiveError(f"archive_secret_value:{path.name}")
    for match in SECRET_KEYS.finditer(text):
        # A field *named* like a secret is only a finding when it carries a value.
        tail = text[match.end(): match.end() + 80]
        if re.match(r"\"?\s*:\s*\"[^\"]{8,}\"", tail):
            raise ArchiveError(f"archive_secret_field:{path.name}")


def _sources(project_root=None):
    for name, parts, kind in SOURCES:
        path = runtime_env.data_path(*parts, project_root=project_root)
        if kind == "file":
            if path.is_file():
                yield name, path, Path(name) / path.name
        elif path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_file():
                    yield name, child, Path(name) / child.name


def freeze(*, project_root=None, frozen_at=None, note="") -> dict:
    """Copy the old registry into a new, checksummed archive directory."""
    entries, missing = [], []
    for name, parts, kind in SOURCES:
        path = runtime_env.data_path(*parts, project_root=project_root)
        if not path.exists():
            missing.append({"source": name, "path": str(Path(*parts))})
    stamp = frozen_at or _now()
    target = archive_root(project_root) / stamp
    if target.exists():
        raise ArchiveError(f"archive_exists:{stamp}")
    staging = target.with_name(target.name + ".partial")
    if staging.exists():
        shutil.rmtree(staging)
    for name, path, relative in _sources(project_root):
        _refuse_secrets(path)
        destination = staging / "files" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        entries.append({"source": name, "file": relative.as_posix(), "origin": str(path),
                        "bytes": destination.stat().st_size, "sha256": _digest(destination),
                        "records": _records(destination)})
    if not entries:
        shutil.rmtree(staging, ignore_errors=True)
        raise ArchiveError("archive_empty")
    manifest = {
        "schema_version": 1,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "archive_id": stamp,
        "note": str(note or ""),
        "read_only": True,
        "files": entries,
        "missing_sources": missing,
        "totals": {"files": len(entries), "records": sum(entry["records"] for entry in entries),
                   "bytes": sum(entry["bytes"] for entry in entries)},
    }
    (staging / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (staging / "README.md").write_text(
        "# Архив старого реестра «AI агенты»\n\n"
        "Только для чтения. Копия, снятая " + manifest["frozen_at_utc"] + ".\n\n"
        "Здесь видно, как система была устроена раньше: какие были модели, какие роли им были\n"
        "назначены, что они выполняли, сколько это стоило и как их оценивали. Ни router, ни\n"
        "coordinator, ни рейтинги текущих назначений, ни исполнение задач этот каталог не читают.\n\n"
        "Целостность проверяется по `MANIFEST.json` (SHA-256 каждого файла).\n",
        encoding="utf-8")
    staging.rename(target)
    return manifest


def archives(project_root=None) -> list:
    root = archive_root(project_root)
    if not root.is_dir():
        return []
    found = []
    for child in sorted(root.iterdir(), reverse=True):
        manifest = child / "MANIFEST.json"
        if child.is_dir() and manifest.is_file():
            try:
                found.append(json.loads(manifest.read_text(encoding="utf-8")))
            except ValueError:
                continue
    return found


def latest(project_root=None):
    found = archives(project_root)
    return found[0] if found else None


def path_of(archive_id, *parts, project_root=None) -> Path:
    return archive_root(project_root).joinpath(str(archive_id), *[str(part) for part in parts])


def verify(archive_id=None, *, project_root=None) -> dict:
    """Re-hash the archive, so a silent change cannot pass as history."""
    manifest = latest(project_root) if archive_id is None else _manifest(archive_id, project_root)
    if not manifest:
        return {"ok": False, "reason": "archive_missing", "drift": []}
    drift = []
    for entry in manifest["files"]:
        path = path_of(manifest["archive_id"], "files", *entry["file"].split("/"), project_root=project_root)
        if not path.is_file():
            drift.append({"file": entry["file"], "problem": "missing"})
        elif _digest(path) != entry["sha256"]:
            drift.append({"file": entry["file"], "problem": "changed"})
    return {"ok": not drift, "archive_id": manifest["archive_id"], "frozen_at_utc": manifest["frozen_at_utc"],
            "files": len(manifest["files"]), "drift": drift}


def _manifest(archive_id, project_root=None):
    path = path_of(archive_id, "MANIFEST.json", project_root=project_root)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_json(archive_id, relative, *, project_root=None):
    path = path_of(archive_id, "files", *str(relative).split("/"), project_root=project_root)
    return json.loads(path.read_text(encoding="utf-8"))


def read_rows(archive_id, source="usage", *, project_root=None) -> list:
    """Every JSONL row of one source, in file order, from the archive alone."""
    manifest = _manifest(archive_id, project_root)
    rows = []
    for entry in (manifest or {}).get("files", []):
        if entry["source"] != source or not entry["file"].endswith(".jsonl"):
            continue
        path = path_of(archive_id, "files", *entry["file"].split("/"), project_root=project_root)
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    rows.append({"_unparsed": line})
    return rows


def agents(archive_id, *, project_root=None) -> list:
    manifest = _manifest(archive_id, project_root)
    for entry in (manifest or {}).get("files", []):
        if entry["source"] == "registry":
            document = read_json(archive_id, entry["file"], project_root=project_root)
            return list(document.get("agents") or []) if isinstance(document, dict) else []
    return []
