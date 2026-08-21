"""Is the running LOCAL process actually the code in the checkout?

The project rule is that every change is developed and run on LOCAL first, then
promoted DEVELOPMENT -> CANARY -> PRODUCTION as one immutable artifact. That
rule quietly breaks whenever LOCAL keeps serving an old process after a merge:
Canary ends up newer than the machine the work is supposed to happen on, and
the three environments start feeling like three different products. It is not a
hypothetical -- LOCAL was found serving 0.10.0-beta.20 while the checkout was
at beta.26, six releases behind.

Nothing here restarts anything. A background process that decides on its own to
restart the server someone is debugging is worse than a stale banner. This
module answers one question honestly, and the interface offers the action.

Development only. Canary and Production run a released artifact and have no
checkout to compare against, so the question is meaningless there and the
answer says so rather than inventing one.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict

from . import runtime_env


STATE_CURRENT = "current"
STATE_STALE = "stale"
STATE_DIRTY = "dirty"
STATE_NOT_APPLICABLE = "not_applicable"
STATE_UNKNOWN = "unknown"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _git(*args: str) -> str:
    """Run git in the checkout, or return "" if it cannot be asked.

    UTF-8 is forced: git reports paths as UTF-8 and this checkout lives under a
    non-ASCII directory name, so the console locale would corrupt the output and
    a clean tree would read as dirty.
    """
    try:
        done = subprocess.run(
            ["git", *args], cwd=_project_root(), text=True,
            encoding="utf-8", errors="replace", capture_output=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if done.returncode != 0:
        return ""
    return done.stdout.strip()


def _dirty_paths() -> list:
    """Working-tree changes, excluding what the app rewrites about itself.

    The server regenerates data/governance-rendered on startup, so counting it
    would make a freshly started LOCAL permanently "dirty" and the signal would
    be ignored within a day.
    """
    raw = _git("status", "--porcelain")
    if not raw:
        return []
    paths = []
    for line in raw.splitlines():
        path = line[3:].strip() if len(line) > 3 else ""
        if not path:
            continue
        if "data/governance-rendered" in path or path.startswith("NT-Analyzer/data/"):
            continue
        paths.append(path)
    return paths


def status() -> Dict[str, Any]:
    """What LOCAL is running against what the checkout holds."""
    if not runtime_env.is_development():
        return {
            "state": STATE_NOT_APPLICABLE,
            "reason": "server_environment",
            "message": ("Canary и Production выполняют неизменяемый артефакт "
                        "релиза; локального checkout для сравнения нет."),
        }

    deployment = runtime_env.public_status()
    running_commit = str(deployment.get("git_commit_sha") or "").strip()
    running_version = str(deployment.get("app_version") or "").strip()

    head_commit = _git("rev-parse", "HEAD")
    head_branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if not head_commit:
        return {
            "state": STATE_UNKNOWN,
            "reason": "git_unavailable",
            "message": "Не удалось прочитать состояние checkout.",
            "running_version": running_version,
            "running_commit": running_commit,
        }

    dirty = _dirty_paths()
    same = bool(running_commit) and running_commit == head_commit

    if not same:
        state, message = STATE_STALE, (
            "LOCAL выполняет не тот код, который лежит в checkout. "
            "Перезапустите LOCAL, иначе разработка идёт не на том, что вы правите.")
    elif dirty:
        state, message = STATE_DIRTY, (
            "В рабочем дереве есть незакоммиченные изменения. Нельзя надёжно "
            "определить, какие из них уже загружены запущенным процессом. "
            "Перед релизом зафиксируйте изменения и перезапустите LOCAL из "
            "чистого commit.")
    else:
        state, message = STATE_CURRENT, "LOCAL соответствует текущему checkout."

    return {
        "state": state,
        "message": message,
        "running_version": running_version,
        "running_commit": running_commit,
        "running_commit_short": running_commit[:12],
        "head_commit": head_commit,
        "head_commit_short": head_commit[:12],
        "head_branch": head_branch,
        "dirty_paths": dirty[:20],
        "dirty_count": len(dirty),
        # The interface offers this; nothing here acts on it. A process that
        # restarts the server being debugged is worse than a stale banner.
        "restart_hint": "start.ps1",
    }


def is_stale() -> bool:
    return status().get("state") == STATE_STALE
