"""What a release actually contains, in the owner's words.

The Release Center could say which artifact was where but not what was in it,
so the only way to answer "what am I about to publish" was to read commit SHAs.
This reads the changelog entry that already ships with the release and returns
a title and at most three points.

Nothing here invents text. If the release has no changelog entry the summary is
empty and the card simply shows no summary, which is honest; a generated
paraphrase of a diff would read like fact while being a guess.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_POINTS = 3

# docs/changelog/2026-08-31-beta80-legal-package-and-preauth-documents.md
_CHANGELOG_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}-beta(\d+)-", re.ASCII)
_VERSION_BETA = re.compile(r"beta\.(\d+)", re.ASCII)
_BULLET = re.compile(r"^\s*[-*•]\s+(.*\S)\s*$")
_HEADING = re.compile(r"^\s*#{1,6}\s+(.*\S)\s*$")
# "# beta.80 — юридический пакет" -> "юридический пакет"
_TITLE_PREFIX = re.compile(r"^beta\.?\d+\s*(?:→\s*beta\.?\d+\s*)?[—:-]\s*", re.IGNORECASE)


def _changelog_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "docs" / "changelog"


def _beta_number(version: str) -> str:
    match = _VERSION_BETA.search(str(version or ""))
    return match.group(1) if match else ""


def _entry_for(version: str, directory: Optional[Path] = None) -> Optional[Path]:
    wanted = _beta_number(version)
    if not wanted:
        return None
    root = directory or _changelog_dir()
    try:
        names = sorted(item.name for item in root.iterdir() if item.is_file())
    except OSError:
        return None
    for name in reversed(names):
        match = _CHANGELOG_NAME.match(name)
        if match and match.group(1) == wanted:
            return root / name
    return None


def _strip_markdown(text: str) -> str:
    """Plain text for a card: links become their label, emphasis is dropped."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[`*_]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse(markdown: str) -> Dict[str, Any]:
    """Title plus the first bullet list, capped at MAX_POINTS."""
    title = ""
    points: List[str] = []
    in_list = False
    for raw in str(markdown or "").splitlines():
        heading = _HEADING.match(raw)
        if heading:
            if not title:
                title = _TITLE_PREFIX.sub("", _strip_markdown(heading.group(1)))
            # A heading closes the first list; later sections are commentary.
            if in_list:
                break
            continue
        bullet = _BULLET.match(raw)
        if bullet:
            in_list = True
            if len(points) < MAX_POINTS:
                points.append(_strip_markdown(bullet.group(1)))
            continue
        if in_list and raw.strip():
            # A non-bullet, non-blank line ends the list.
            break
    return {"title": title, "points": points}


def summary_for(version: str, *, directory: Optional[Path] = None) -> Dict[str, Any]:
    """Release summary for a version, or empty when nothing is recorded."""
    entry = _entry_for(version, directory)
    if entry is None:
        return {"title": "", "points": [], "source": ""}
    try:
        markdown = entry.read_text(encoding="utf-8-sig")
    except OSError:
        return {"title": "", "points": [], "source": ""}
    parsed = parse(markdown)
    parsed["source"] = entry.name
    return parsed
