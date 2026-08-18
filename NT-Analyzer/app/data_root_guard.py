"""One active data root, provable rather than assumed.

``runtime_env.data_root()`` is deterministic given its environment variables.
That is exactly the trap: a tool started without them resolves a *different*
directory and reports confidently on a store nothing serves. It happened here.
``start.ps1`` exports ``STRATFORGE_DEVELOPMENT_DATA_ROOT=<project>/data``; an
ad-hoc process without it resolved ``<project>/data/development``, an abandoned
copy last written weeks earlier, and produced a complete but entirely fictional
account inventory.

The resolver was never wrong. What was missing was any way to tell that the
answer came from a different question, so this module adds two things:

* the running server **publishes** which root it is actually serving;
* tooling **verifies** its own answer against that, and refuses to proceed when
  several plausible roots exist and none can be proven active.

Fail closed, deliberately: a maintenance tool that guesses wrong writes to the
wrong store, and a cleanup performed on the wrong store is worse than one that
did not run.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import runtime_env


# Written into the active root by the server at startup.
ACTIVE_MARKER = ".stratforge-active-root.json"
# Placed by hand (or by mark_legacy) into a root that must never be picked up
# again. Kept rather than deleted: an abandoned store is still evidence.
LEGACY_MARKER = ".stratforge-legacy-root.json"

# Files that make a directory look like a real data root rather than an empty
# folder someone created by accident.
_STORE_SIGNATURES = (
    Path("integrations") / "accounts.dpapi",
    Path("integrations") / "workspaces.dpapi",
    Path("integrations") / "connectors.dpapi",
)


class DataRootError(RuntimeError):
    """Raised instead of operating on a root that cannot be proven active."""


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def looks_like_store(path: Path) -> bool:
    return any((path / signature).is_file() for signature in _STORE_SIGNATURES)


def is_legacy(path: Path) -> bool:
    return (path / LEGACY_MARKER).is_file()


def candidate_roots(project_root: Optional[Path] = None) -> List[Path]:
    """Directories under the project that hold a real store.

    Deliberately not "every directory that could be a root" -- an empty folder
    is not a candidate for anything. What matters is places a tool could
    plausibly resolve to *and* find data in, because those are the ones that
    produce a confident wrong answer.
    """
    base = project_root or _project_root()
    seen: List[Path] = []
    for relative in ("data", Path("data") / "development", Path("data") / "staging"):
        path = (base / relative)
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved not in seen and looks_like_store(resolved):
            seen.append(resolved)
    return seen


def publish_active_root(environment: str = "") -> Optional[Path]:
    """Record which root this process is serving. Called by the server.

    Best effort: a read-only or missing directory must not stop the server from
    starting, since the marker is a diagnostic aid rather than a dependency.
    """
    try:
        root = Path(runtime_env.data_root())
        root.mkdir(parents=True, exist_ok=True)
        payload = {
            "environment": environment or runtime_env.deployment_environment(),
            "published_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pid": os.getpid(),
            "root": str(root),
        }
        (root / ACTIVE_MARKER).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return root
    except Exception:
        return None


def read_marker(path: Path) -> Dict[str, Any]:
    try:
        return json.loads((path / ACTIVE_MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def inspect(project_root: Optional[Path] = None) -> Dict[str, Any]:
    """Everything a caller needs to judge the situation, without deciding."""
    resolved = Path(runtime_env.data_root())
    candidates = candidate_roots(project_root)
    published = [p for p in candidates if (p / ACTIVE_MARKER).is_file()]
    legacy = [p for p in candidates if is_legacy(p)]
    live = [p for p in candidates if p not in legacy]
    return {
        "resolved": resolved,
        "candidates": candidates,
        "published": published,
        "legacy": legacy,
        "live": live,
        "resolved_is_published": (resolved / ACTIVE_MARKER).is_file(),
        "marker": read_marker(resolved),
    }


def require_active_root(project_root: Optional[Path] = None) -> Path:
    """The data root, or an exception naming why it cannot be trusted.

    Every maintenance, migration and diagnostic tool goes through this instead
    of calling ``runtime_env.data_root()`` directly, so that all of them answer
    the same question the server answered.
    """
    state = inspect(project_root)
    resolved: Path = state["resolved"]
    live: List[Path] = state["live"]

    if is_legacy(resolved):
        raise DataRootError(
            f"Resolved data root {resolved} is marked legacy. Export the same "
            "STRATFORGE_*_DATA_ROOT values the server uses (see start.ps1)."
        )

    # Proven: the server published this exact root.
    if state["resolved_is_published"]:
        return resolved

    # Only one live store exists, and this is it -- nothing to confuse it with.
    if live == [resolved]:
        return resolved

    others = [str(p) for p in live if p != resolved]
    if others:
        raise DataRootError(
            f"Cannot prove which data root is active. Resolved {resolved}, but "
            f"these also hold stores: {', '.join(others)}. Start the server "
            "once so it publishes its root, or export the same "
            "STRATFORGE_*_DATA_ROOT values it uses."
        )
    raise DataRootError(
        f"Resolved data root {resolved} holds no store and none is published. "
        "Export the same STRATFORGE_*_DATA_ROOT values the server uses."
    )


def mark_legacy(path: Path, reason: str) -> Path:
    """Retire a store without deleting it.

    Deleting would destroy evidence -- an abandoned store is often the only
    record of what a deployment used to look like. Marking removes it from
    automatic selection while leaving it readable on purpose.
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    marker = path / LEGACY_MARKER
    marker.write_text(
        json.dumps({
            "reason": str(reason or "")[:400],
            "marked_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return marker
