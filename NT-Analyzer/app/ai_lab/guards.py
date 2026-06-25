"""Sandbox-only write guard.

The AI pipeline must NEVER write into production strategy folders. Any disk
write that targets a path outside the canonical AI sandbox directory or its
in-repo mirror raises :class:`SandboxBreachError`. ``generator.write_to_sandbox``
calls :func:`assert_sandbox_only` before writing.
"""

from __future__ import annotations

from pathlib import Path

from . import paths


class SandboxBreachError(Exception):
    """Raised when a write would land outside the AI sandbox or mirror."""


def _resolve(p) -> Path:
    return Path(p).resolve()


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def assert_sandbox_only(path) -> None:
    target = _resolve(path)
    sandbox = _resolve(paths.ai_sandbox_strategies_dir())
    mirror = _resolve(paths.SOURCE_SNAPSHOTS_DIR)
    if _is_within(target, sandbox) or _is_within(target, mirror):
        return
    raise SandboxBreachError(
        f"AI tried to write outside sandbox: {target} "
        f"(allowed: {sandbox} or {mirror})"
    )
