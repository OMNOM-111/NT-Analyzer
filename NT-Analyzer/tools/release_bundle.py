"""The exact file set a server release ships, in one place.

The builder used to own this list privately, so nothing else could ask what a
release actually contains. Local checks then ran against the repository while
the signer's build ran inside the bundle, and the two disagreed: markdown links
that resolve in a checkout pointed outside the artifact, and the failure only
appeared on the protected signer as an unexplained executor error.

Both the builder and the pre-release check import this module, so the answer
cannot drift between them. Deliberately free of signing dependencies: the check
must run on a developer machine that has no release key and no `cryptography`.
"""
from __future__ import annotations

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent


# Trees the running service reads at runtime, not just sources. docs/legal is
# served pre-auth on the registration screen and docs/changelog backs the
# release summary; an artifact missing either leaves the deployed service
# unable to answer something the UI asks it for.
_INCLUDED_TREES = ("app", "ai_lab", "data", "deploy", "docs/governance", "docs/legal",
                   "docs/changelog")
_INCLUDED_FILES = (
    "README.md",
    "README-RUN-MODES.md",
    "VERSION.json",
    "requirements.txt",
    "docs/strategies/AI_STRATEGY_LAB_QUALITY.md",
    "docs/strategies/AI_STRATEGY_LAB_RUN_CONTROLS.md",
    "docs/operations/CONNECTOR_INSTALL_GUIDE.md",
    "docs/architecture/CONNECTOR_PROTOCOL_V1.md",
    "docs/operations/MARKET_DATA_PRODUCTION_RUNBOOK.md",
    "docs/operations/PRODUCTION_DEPLOYMENT_RUNBOOK.md",
    "docs/operations/PRODUCTION_OPERATIONS_RUNBOOK.md",
    "docs/operations/PRODUCTION_STORAGE_RUNBOOK.md",
    "docs/operations/PRODUCTION_TELEGRAM_RUNBOOK.md",
    "docs/operations/PRODUCTION_WORKER_RUNBOOK.md",
    "docs/strategies/risk-profile.md",
    # Registry documents with audience "user": listed and served by the
    # Documents API, so an artifact without them serves an empty page. The rest
    # of docs/agents is deliberately not shipped, which is why these are named
    # individually rather than by including the tree.
    "docs/agents/AI_LAB_CLOUD_AGENTS.md",
    "docs/agents/AI_LAB_COMPETITIVE_FEEDBACK.md",
    "tools/production_preflight.py",
    "tools/production_storage_cli.py",
    "tools/canary_blue_green_promote.sh",
    "tools/production_blue_green_promote.sh",
    "tools/production_blue_green_rollback.sh",
    "tools/canary_isolation_provision.py",
    "tools/canary_manifest_trust.py",
    "tools/release_static_scan.py",
    "tools/verify_server_release.py",
    "tools/owner_model_migrate.py",
)
# docs/legal ships so the pre-auth registration screen can serve the public
# package, but the owner-only configuration must never leave the repository.
_EXCLUDED_FILES = {
    "docs/agents/AGENTS.md",
    "docs/AI_DIALOGUE_CONTRACT.md",
    "docs/legal/OWNER_LEGAL_CONFIGURATION.md",
}

def _selected_files(root: Path) -> list[Path]:
    pathspecs = [*_INCLUDED_TREES, *_INCLUDED_FILES]
    raw = subprocess.check_output(
        ["git", "ls-files", "-z", "--", *pathspecs], cwd=root,
    ).decode("utf-8", errors="surrogateescape")
    selected: list[Path] = []
    for value in sorted(item for item in raw.split("\0") if item):
        relative = Path(value)
        normalized = relative.as_posix()
        if normalized in _EXCLUDED_FILES:
            continue
        source = root / relative
        if source.is_symlink():
            raise RuntimeError(f"release source symlinks are forbidden: {normalized}")
        if not source.is_file():
            raise RuntimeError(f"tracked release source is missing: {normalized}")
        selected.append(relative)
    required = {
        "app/server.py",
        "app/production_workers.py",
        "app/production_telegram.py",
        "app/observability.py",
        "deploy/production/stratforge.service",
        "deploy/production/stratforge-worker.service",
        "deploy/production/stratforge-telegram.service",
        "deploy/production/stratforge-operations.timer",
        "tools/production_preflight.py",
        "tools/canary_blue_green_promote.sh",
        "tools/production_blue_green_promote.sh",
        "tools/production_blue_green_rollback.sh",
        "tools/canary_manifest_trust.py",
        "requirements.txt",
        "VERSION.json",
    }
    present = {path.as_posix() for path in selected}
    missing = sorted(required - present)
    if missing:
        raise RuntimeError("incomplete server release selection: " + ", ".join(missing))
    return selected
