"""The strategy-development knowledge the AI Lab already relies on, as fragments.

Rules of strategy development, distilled lessons, the reference strategy
library and the owner's research materials are Markdown files. This module
only reads them and splits each document into section-sized fragments, so the
AI Center can show and count them; it never writes, calls a model or changes
what the Lab reads.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from . import paths
from .io_utils import iter_jsonl

# Fragment kinds follow the AI Center legend. The registry is the history of
# the owner's own strategies; the reference library holds public samples that
# only compile and pass checks - neither is a proven strategy by itself.
RULE, REGISTRY, LESSON, REFERENCE, DATA = "rule", "registry", "lesson", "reference", "data"
REGISTRY_DOCUMENT = "Реестр стратегий.md"
_SECTION = re.compile(r"^##\s+(.+?)\s*$", re.M)
_TITLE = re.compile(r"^#\s+(.+?)\s*$", re.M)
# Service sections of the documents, not knowledge of their own.
_SKIP_SECTIONS = {"purpose", "ai metadata", "identification", "source", "sources", "critical read before any ai-cell generation"}
_cache: Dict[str, Any] = {"key": None, "value": None}


def strategy_rules_dirs() -> List[Path]:
    """Where the owner's «РАЗРАБОТКА СТРАТЕГИЙ» documents live.

    The data root copy comes first; the folder next to the project checkout is
    the historical location and still read when present.
    """
    candidates = [paths.MUTABLE_AI_LAB_DIR / "strategy_rules",
                  paths.PROJECT_ROOT.parent / "РАЗРАБОТКА СТРАТЕГИЙ"]
    seen, found = set(), []
    for path in candidates:
        key = str(path.resolve()) if path.exists() else ""
        if key and key not in seen and path.is_dir():
            seen.add(key)
            found.append(path)
    return found


def _sources() -> List[Tuple[str, Path]]:
    files: List[Tuple[str, Path]] = []
    for folder in strategy_rules_dirs():
        files.extend((REGISTRY if path.name == REGISTRY_DOCUMENT else RULE, path) for path in sorted(folder.glob("*.md")))
    lessons = paths.REFERENCE_STRATEGIES_DIR / "ai_lessons"
    if lessons.is_dir():
        # The summary of rules leads; per-experiment post-mortems follow.
        files.extend((LESSON, path) for path in sorted(lessons.glob("*.md"), key=lambda path: (path.name != "LESSONS_SUMMARY.md", path.name)))
    if paths.REFERENCE_STRATEGIES_DIR.is_dir():
        files.extend((REFERENCE, path) for path in sorted(paths.REFERENCE_STRATEGIES_DIR.glob("REF-*/normalized_spec.md")))
    research = paths.USER_RESEARCH_DIR / "curated" / "researches"
    if research.is_dir():
        files.extend((DATA, path) for path in sorted(research.glob("*.md")))
    return files


def _plain(text: str, limit: int = 240) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"[`*_>#|]", "", text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _stamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")


def _fragments(kind: str, path: Path) -> Iterable[Dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    heading = _TITLE.search(text)
    document = (heading.group(1) if heading else path.stem).strip()
    if kind == REFERENCE:
        document = re.sub(r"^Normalized Spec:\s*", "", document)
    source = path.parent.name + "/" + path.name if kind == REFERENCE else path.name
    base = {"kind": kind, "document": document, "source": source, "updated_at": _stamp(path)}
    if kind in {REFERENCE, DATA}:
        # One fragment per strategy or research material: its first sections.
        sections = _SECTION.split(text)
        body = " ".join(sections[index + 1] for index in range(1, len(sections) - 1, 2)
                        if sections[index].strip().lower() not in _SKIP_SECTIONS)
        return [{**base, "id": f"{kind}:{source}", "title": document, "summary": _plain(body)}]
    parts = _SECTION.split(text)
    rows = []
    for index in range(1, len(parts) - 1, 2):
        title, body = parts[index].strip(), parts[index + 1]
        if title.lower() in _SKIP_SECTIONS or not _plain(body):
            continue
        rows.append({**base, "id": f"{kind}:{source}#{len(rows) + 1}", "title": title, "summary": _plain(body)})
    return rows or [{**base, "id": f"{kind}:{source}", "title": document, "summary": _plain(text)}]


def _logged_lessons() -> List[Dict[str, Any]]:
    rows = []
    for index, record in enumerate(iter_jsonl(paths.LESSON_LOG_PATH)):
        summary = str(record.get("summary") or "").strip()
        if summary:
            rows.append({"kind": LESSON, "id": f"lesson_log:{record.get('lesson_id') or index}", "document": "Журнал уроков Лаборатории",
                         "source": "lesson_log.jsonl", "title": _plain(summary, 120), "summary": _plain(str(record.get("rule") or summary)),
                         "updated_at": str(record.get("timestamp_utc") or "")})
    return rows


def snapshot() -> Dict[str, Any]:
    """All fragments with their counts; re-read only when a source file changes."""
    files = _sources()
    lesson_log = paths.LESSON_LOG_PATH
    key = tuple((str(path), path.stat().st_mtime_ns) for _, path in files) + (
        (str(lesson_log), lesson_log.stat().st_mtime_ns) if lesson_log.exists() else ("", 0),)
    if _cache["key"] == key:
        return _cache["value"]
    items: List[Dict[str, Any]] = []
    for kind, path in files:
        items.extend(_fragments(kind, path))
    items.extend(_logged_lessons())
    count = lambda kind: sum(1 for item in items if item["kind"] == kind)  # noqa: E731
    value = {
        "items": items,
        "fragments": len(items),
        "rules": count(RULE),
        "registry": count(REGISTRY),
        "lessons": count(LESSON),
        "references": count(REFERENCE),
        "materials": count(DATA),
        "documents": len(files) + (1 if any(item["source"] == "lesson_log.jsonl" for item in items) else 0),
        "rules_found": bool(strategy_rules_dirs()),
    }
    _cache.update(key=key, value=value)
    return value


def brief(limit: int = 3) -> Dict[str, Any]:
    """Counts and the first lessons, small enough for the overview."""
    value = snapshot()
    logged = [item for item in value["items"] if item["source"] == "lesson_log.jsonl"][::-1]
    lessons = (logged + [item for item in value["items"] if item["kind"] == LESSON and item not in logged])[:limit]
    return {key: value[key] for key in ("fragments", "rules", "registry", "lessons", "references", "materials", "documents", "rules_found")} | {
        "latest": [{"id": item["id"], "title": item["title"], "document": item["document"], "updated_at": item["updated_at"]} for item in lessons]}

