#!/usr/bin/env python3
"""Export the canonical External GPT Context Pack for owner upload use.

The canonical source remains repository-root ``AI_CONTEXT/``. This tool copies
exactly the 15 canonical markdown files into a local owner-facing export folder
after first validating the pack.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import validate_external_gpt_context  # noqa: E402


EXPORT_DIR_DEFAULT = Path.home() / "Desktop" / "StratForge External GPT Context"
MANIFEST_NAME = ".stratforge_external_gpt_export_manifest.json"
INFO_NAME = "EXPORT_INFO.txt"
EXPORT_DOCS = list(validate_external_gpt_context.REQUIRED_DOCS)
SOURCE_DIR = validate_external_gpt_context.PACK_DIR


class ExportError(RuntimeError):
    """Raised when the external GPT context export cannot be completed."""


@dataclass
class ExportResult:
    output_dir: Path
    exported_docs: list[str]
    git_sha: str
    exported_at_utc: str
    warnings: list[str]


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
    )
    if completed.returncode != 0:
        raise ExportError("failed to determine current Git SHA")
    return completed.stdout.strip().lower()


def _manifest_path(output_dir: Path) -> Path:
    return output_dir / MANIFEST_NAME


def _info_path(output_dir: Path) -> Path:
    return output_dir / INFO_NAME


def _load_manifest(output_dir: Path) -> dict[str, object] | None:
    path = _manifest_path(output_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExportError(f"invalid export manifest: {path}") from exc
    if not isinstance(data, dict):
        raise ExportError(f"invalid export manifest shape: {path}")
    return data


def _ensure_no_unmanaged_collisions(output_dir: Path) -> None:
    collisions: list[str] = []
    for name in EXPORT_DOCS + [INFO_NAME]:
        if (output_dir / name).exists():
            collisions.append(name)
    if collisions:
        joined = ", ".join(collisions)
        raise ExportError(
            f"export folder contains unmanaged files with managed names: {joined}; "
            f"move them away or rerun after a manifest-backed export"
        )


def _clean_previous_export(output_dir: Path, manifest: dict[str, object] | None) -> None:
    if manifest is None:
        _ensure_no_unmanaged_collisions(output_dir)
        return

    managed_docs = manifest.get("exported_docs")
    if not isinstance(managed_docs, list):
        raise ExportError("invalid export manifest: exported_docs must be a list")

    allowed = set(EXPORT_DOCS + [INFO_NAME])
    for name in managed_docs + [INFO_NAME]:
        if not isinstance(name, str) or name not in allowed or Path(name).name != name:
            continue
        path = output_dir / name
        if path.is_file():
            path.unlink()

    manifest_path = _manifest_path(output_dir)
    if manifest_path.exists():
        manifest_path.unlink()


def _write_manifest(output_dir: Path, git_sha: str, exported_at_utc: str) -> None:
    payload = {
        "tool": "export_external_gpt_context.py",
        "canonical_source": str(SOURCE_DIR.relative_to(ROOT.parent)).replace("\\", "/"),
        "git_sha": git_sha,
        "exported_at_utc": exported_at_utc,
        "exported_docs": EXPORT_DOCS,
    }
    _manifest_path(output_dir).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_info(output_dir: Path, git_sha: str, exported_at_utc: str) -> None:
    text = (
        f"Exported UTC: {exported_at_utc}\n"
        f"Git SHA: {git_sha}\n"
        f"Canonical source: {str(SOURCE_DIR).replace('\\', '/')}\n"
        "Instruction: В ChatGPT Project загрузить 15 `.md` файлов; `EXPORT_INFO.txt` не нужен.\n"
    )
    _info_path(output_dir).write_text(text, encoding="utf-8")


def export(output_dir: Path = EXPORT_DIR_DEFAULT) -> ExportResult:
    validation = validate_external_gpt_context.validate()
    if validation.errors:
        raise ExportError("context pack validation failed: " + "; ".join(validation.errors))

    missing = [name for name in EXPORT_DOCS if not (SOURCE_DIR / name).is_file()]
    if missing:
        raise ExportError("missing canonical context documents: " + ", ".join(missing))

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(output_dir)
    _clean_previous_export(output_dir, manifest)

    for name in EXPORT_DOCS:
        shutil.copy2(SOURCE_DIR / name, output_dir / name)

    exported = sorted(path.name for path in output_dir.glob("*.md") if path.name in EXPORT_DOCS)
    if exported != EXPORT_DOCS:
        raise ExportError(
            f"export count mismatch: expected {len(EXPORT_DOCS)} canonical markdown files, got {len(exported)}"
        )

    git_sha = _git_head()
    exported_at_utc = _now_utc()
    _write_info(output_dir, git_sha=git_sha, exported_at_utc=exported_at_utc)
    _write_manifest(output_dir, git_sha=git_sha, exported_at_utc=exported_at_utc)

    return ExportResult(
        output_dir=output_dir,
        exported_docs=exported,
        git_sha=git_sha,
        exported_at_utc=exported_at_utc,
        warnings=validation.warnings,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default=str(EXPORT_DIR_DEFAULT),
        help="Owner-facing export folder. Default: %(default)s",
    )
    args = parser.parse_args()
    try:
        result = export(Path(args.output_dir))
    except ExportError as exc:
        print(f"EXTERNAL GPT EXPORT FAIL: {exc}")
        return 1
    print(f"EXTERNAL GPT EXPORT OK: {result.output_dir}")
    print(f"EXPORTED FILES: {len(result.exported_docs)}")
    print(f"GIT SHA: {result.git_sha}")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
