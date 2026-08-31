"""Whether a build came from approved main, decided here and nowhere else.

An artifact built from an unmerged branch reached Canary, passed acceptance and
was one enabled button away from Production. Acceptance says the environment is
healthy; it says nothing about where the code came from. Neither does the
version string, which an unmerged branch carries just as truthfully.

So provenance is its own gate, and it asks about the commit rather than about
the release: is this exactly a commit on the synchronised origin/main, was the
worktree clean when it was cut, and did that exact SHA pass the required CI.
A question it cannot answer is answered "no": a promotion that proceeds because
a check could not be run is the failure this exists to prevent.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REMOTE = "origin"
_MAIN = "main"
_TIMEOUT_SEC = 20.0

# Required checks are what branch protection enforces; a run that is missing is
# not a run that passed.
REQUIRED_CONCLUSION = "success"


def _root() -> Path:
    return Path(__file__).resolve().parents[1].parent


def _git(*args: str, timeout: float = _TIMEOUT_SEC) -> tuple[int, str]:
    try:
        done = subprocess.run(
            ["git", *args], cwd=str(_root()), text=True, encoding="utf-8",
            errors="replace", capture_output=True, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return done.returncode, done.stdout.strip()


def _check(name: str, label: str, ok: bool, detail: str) -> Dict[str, Any]:
    return {"name": name, "label": label, "ok": bool(ok), "detail": detail}


def _repository() -> str:
    """owner/repo from the origin remote, for the CI query."""
    code, url = _git("remote", "get-url", _REMOTE)
    if code or not url:
        return ""
    match = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url.strip())
    return match.group(1) if match else ""


def ci_status(commit_sha: str) -> Dict[str, Any]:
    """Required check runs for exactly this SHA.

    Uses the GitHub CLI the rest of this workflow already relies on. When it
    cannot answer -- no CLI, no network, no authentication -- the result is
    "unknown", which callers must treat as not eligible.
    """
    repository = _repository()
    if not repository:
        return {"known": False, "ok": False, "detail": "origin remote не определён"}
    try:
        done = subprocess.run(
            ["gh", "api", f"repos/{repository}/commits/{commit_sha}/check-runs",
             "--jq", ".check_runs[] | .name + \"\\t\" + (.conclusion // \"pending\")"],
            cwd=str(_root()), text=True, encoding="utf-8", errors="replace",
            capture_output=True, timeout=60.0,
        )
    except (OSError, subprocess.SubprocessError):
        return {"known": False, "ok": False, "detail": "gh недоступен"}
    if done.returncode:
        return {"known": False, "ok": False,
                "detail": "CI-статус не получен: " + (done.stderr or "").strip()[:120]}
    runs = []
    for line in (done.stdout or "").splitlines():
        name, _, conclusion = line.partition("\t")
        if name.strip():
            runs.append((name.strip(), conclusion.strip()))
    if not runs:
        return {"known": True, "ok": False, "detail": "для этого SHA нет ни одного check run"}
    failed = [name for name, conclusion in runs if conclusion != REQUIRED_CONCLUSION]
    if failed:
        return {"known": True, "ok": False,
                "detail": "не пройдены: " + ", ".join(sorted(failed)[:5])}
    return {"known": True, "ok": True, "detail": f"{len(runs)} проверок пройдено"}


def evaluate(commit_sha: str = "", *, ci: Optional[Any] = None) -> Dict[str, Any]:
    """Every condition a production-eligible build has to meet.

    Returns each check separately so the panel can state which one refused
    rather than only that something did.
    """
    checks: List[Dict[str, Any]] = []
    sha = str(commit_sha or "").strip().lower()

    code, head = _git("rev-parse", "HEAD")
    head = head.lower() if not code else ""
    if not sha:
        sha = head
    checks.append(_check("commit_known", "Commit определён", bool(_SHA_RE.match(sha)),
                         sha[:12] or "неизвестен"))

    code, branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    on_main = (not code) and branch == _MAIN
    checks.append(_check("branch_is_main", "Ветка main", on_main,
                         branch or "неизвестна"))

    code, dirty = _git("status", "--porcelain")
    clean = (not code) and not dirty.strip()
    checks.append(_check("worktree_clean", "Чистое рабочее дерево", clean,
                         "без изменений" if clean else "есть незакоммиченные изменения"))

    # Compared against the fetched remote ref rather than a local branch, so a
    # local main that was never pushed cannot pass as synchronised.
    _git("fetch", _REMOTE, _MAIN, "--quiet", timeout=30.0)
    code, counts = _git("rev-list", "--left-right", "--count",
                        f"{_REMOTE}/{_MAIN}...HEAD")
    behind = ahead = -1
    if not code and counts:
        parts = counts.split()
        if len(parts) == 2:
            behind, ahead = int(parts[0]), int(parts[1])
    in_sync = behind == 0 and ahead == 0
    checks.append(_check(
        "in_sync_with_origin_main", "Синхронизирован с origin/main", in_sync,
        "совпадает" if in_sync
        else (f"отстаёт на {behind}, опережает на {ahead}" if behind >= 0
              else "состояние не определено")))

    code, _ = _git("merge-base", "--is-ancestor", sha, f"{_REMOTE}/{_MAIN}")
    on_origin_main = code == 0 and bool(_SHA_RE.match(sha))
    checks.append(_check("commit_on_origin_main", "Commit входит в origin/main",
                         on_origin_main,
                         "да" if on_origin_main else "коммита нет в origin/main"))

    status = (ci or ci_status)(sha) if _SHA_RE.match(sha) else {
        "known": False, "ok": False, "detail": "SHA неизвестен"}
    checks.append(_check("ci_green", "CI для этого SHA",
                         bool(status.get("ok")), str(status.get("detail") or "")))

    blocking = [row for row in checks if not row["ok"]]
    return {
        "eligible": not blocking,
        "commit": sha,
        "checks": checks,
        "blocking": [row["name"] for row in blocking],
        "reason": "" if not blocking else
                  "Эта сборка не создана из утверждённого main: "
                  + "; ".join(f"{row['label']} — {row['detail']}" for row in blocking),
    }


# Production has three states, and only one of them permits a comparison-free
# publication. "No Production yet" is a genuine first deployment. "Production
# exists but its identity could not be read" is a question we failed to answer,
# and answering it optimistically is how a rollback gets published by accident.
PRODUCTION_ABSENT = "absent"
PRODUCTION_KNOWN = "known"
PRODUCTION_UNKNOWN = "unknown"

_DEPLOYED_STATES = frozenset({"production_live", "production_deploying", "rolled_back"})


def production_identity(registry: Any = None, releases: Any = None) -> Dict[str, Any]:
    """What Production is running, and whether that could be determined at all.

    Preferred source is what Production reports about itself; the release
    ledger's deployment history is the fallback for the window before an
    environment has checked in. Evidence that Production exists is kept
    separate from the commit itself, so an unreadable identity cannot be
    mistaken for an empty one.
    """
    rows = [row for row in ((registry or {}).get("environments") or [])
            if str(row.get("environment") or "") == "production"]
    history = [row for row in ((releases or {}).get("releases") or [])
               if str(row.get("state") or "") in _DEPLOYED_STATES]

    for row in rows:
        sha = str(row.get("git_commit_sha") or "").strip().lower()
        if _SHA_RE.match(sha):
            return {"state": PRODUCTION_KNOWN, "commit": sha, "source": "environment"}
    for row in history:
        sha = str(row.get("git_commit_sha") or "").strip().lower()
        if _SHA_RE.match(sha):
            return {"state": PRODUCTION_KNOWN, "commit": sha, "source": "ledger"}
    if rows or history:
        return {"state": PRODUCTION_UNKNOWN, "commit": "", "source": ""}
    return {"state": PRODUCTION_ABSENT, "commit": "", "source": ""}


def forward_only(candidate_sha: str, production: Any) -> Dict[str, Any]:
    """Whether publishing this candidate would move Production forward.

    Provenance asks where the code came from; it cannot tell a current release
    from a superseded one, because an old commit on main is every bit as
    approved as a new one. A candidate built from an earlier main commit
    therefore passes provenance while publishing it would silently roll
    Production back -- which is what an audit found sitting one click away.

    Going back is a rollback, and rollback has its own contract, its own owner
    gate and its own artifact rules. It is not this button.
    """
    candidate = str(candidate_sha or "").strip().lower()
    identity = (production if isinstance(production, dict)
                else production_identity({"environments": [
                    {"environment": "production", "git_commit_sha": str(production or "")}]}
                    if production else None, None))
    state = str(identity.get("state") or PRODUCTION_UNKNOWN)
    live = str(identity.get("commit") or "").strip().lower()

    if not _SHA_RE.match(candidate):
        return {"ok": False, "reason": "Commit кандидата неизвестен.",
                "code": "candidate_commit_unknown", "production": identity}
    if state == PRODUCTION_ABSENT:
        # Genuinely nothing deployed: there is nothing to be older than.
        return {"ok": True, "reason": "", "code": "", "production": identity}
    if state != PRODUCTION_KNOWN or not _SHA_RE.match(live):
        return {
            "ok": False, "production": identity,
            "code": "production_identity_unknown",
            "reason": ("Не удалось определить текущую версию Production. "
                       "Публикация запрещена до восстановления identity."),
        }
    if candidate == live:
        return {"ok": True, "reason": "", "code": "", "production": identity}
    code, _ = _git("merge-base", "--is-ancestor", live, candidate)
    if code == 0:
        return {"ok": True, "reason": "", "code": "", "production": identity}
    return {
        "ok": False, "production": identity,
        "code": "candidate_not_ahead_of_production",
        "reason": ("Эта сборка старее текущего Production "
                   f"({live[:12]}). Для возврата используй Rollback."),
    }


# The panel asks on every poll, and the answer costs a fetch and a CI query.
# Cached briefly per commit: ancestry does not change second to second, and a
# stale-by-a-minute refusal is safe while a stale approval is not -- so only
# eligible answers are cached, and a refusal is re-checked every time.
_CACHE: Dict[str, Any] = {}
_CACHE_TTL_SEC = 60.0


def eligibility(commit_sha: str) -> Dict[str, Any]:
    """Provenance of a candidate's own commit, for the promotion gate."""
    import time

    key = str(commit_sha or "").strip().lower()
    cached = _CACHE.get(key)
    if cached and time.monotonic() - cached["at"] < _CACHE_TTL_SEC:
        return cached["value"]
    value = evaluate(key)
    if value.get("eligible"):
        _CACHE[key] = {"at": time.monotonic(), "value": value}
    return value
