"""Run the signer's release gates locally, inside a real bundle.

Three releases in a row were broken by the same shape of mistake: a check that
passed in the repository and failed in the artifact. `release_static_scan` run
from a checkout resolves every relative link, because the checkout contains
files the bundle does not; the same scan run inside the bundle — which is what
`build_server_release` actually does — fails. The failure then surfaced only on
the protected signer, as a bare `ReleaseExecutorError` with no message.

This assembles the exact production file set into a temporary directory using
the same selection the builder uses, and runs the gates there. A local PASS is
meant to mean the same gates pass on the signing/build node.

It deliberately does not sign, archive or upload anything: it needs no release
key, and it must run on a developer machine that has none.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.release_bundle import ROOT, _selected_files


def materialise(root: Path, destination: Path) -> list[Path]:
    """Copy exactly the shipped files, preserving layout."""
    selected = _selected_files(root)
    for relative in selected:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, target)
    return selected


def _run_static_scan(bundle: Path) -> list[str]:
    """The gate the builder runs, in the place the builder runs it."""
    scan = bundle / "tools" / "release_static_scan.py"
    if not scan.is_file():
        return ["release_static_scan.py is not part of the artifact"]
    completed = subprocess.run(
        [sys.executable, "tools/release_static_scan.py"], cwd=bundle,
        text=True, encoding="utf-8", errors="replace", capture_output=True,
    )
    if completed.returncode == 0:
        return []
    detail = (completed.stdout + "\n" + completed.stderr).strip()
    return [line for line in detail.splitlines() if line.strip()]


def _check_runtime_reads(bundle: Path, shipped: set[str]) -> list[str]:
    """Files the running service reads, which must travel with it.

    Both known escapes were of this kind: the legal package the registration
    screen serves, and the changelog the release summary reads. Neither is
    imported, so nothing failed until a deployed environment tried to read it.
    """
    errors: list[str] = []
    sys.path.insert(0, str(ROOT))
    try:
        from app import governance, release_summary
    except Exception as exc:  # pragma: no cover - import guard
        return [f"cannot inspect runtime reads: {type(exc).__name__}: {exc}"]

    for row in governance.DEFAULT_DOCUMENTS["documents"]:
        if str(row.get("category") or "").lower() != "legal":
            continue
        if str(row.get("audience") or "").lower() != "user" or row.get("draft"):
            continue
        path = str(row.get("path") or "")
        if path and path not in shipped:
            errors.append(f"public legal document not shipped: {path}")

    version = ""
    version_file = bundle / "VERSION.json"
    if version_file.is_file():
        try:
            version = str(json.loads(version_file.read_text(encoding="utf-8")).get("version") or "")
        except ValueError:
            errors.append("VERSION.json in the artifact is not valid JSON")
    if version:
        # Resolve the summary against the bundle, not the repository.
        summary = release_summary.summary_for(
            version, directory=bundle / "docs" / "changelog")
        if not summary["title"]:
            errors.append(
                f"release summary for {version} does not resolve inside the artifact; "
                "the card would show no «Что изменилось»")
    return errors


def _check_python_compiles(bundle: Path) -> list[str]:
    """Every shipped module must at least parse where it will run."""
    completed = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "app"], cwd=bundle,
        text=True, encoding="utf-8", errors="replace", capture_output=True,
    )
    if completed.returncode == 0:
        return []
    detail = (completed.stdout + "\n" + completed.stderr).strip()
    return [line for line in detail.splitlines() if line.strip()][:20]


def check(root: Path = ROOT, *, keep: bool = False) -> dict:
    holder = tempfile.mkdtemp(prefix="stratforge-prerelease-")
    bundle = Path(holder) / "bundle"
    bundle.mkdir(parents=True)
    try:
        selected = materialise(root, bundle)
        shipped = {path.as_posix() for path in selected}
        gates = {
            "static_scan_in_bundle": _run_static_scan(bundle),
            "runtime_reads_shipped": _check_runtime_reads(bundle, shipped),
            "python_compiles": _check_python_compiles(bundle),
        }
        failures = {name: rows for name, rows in gates.items() if rows}
        return {
            "ok": not failures,
            "files": len(selected),
            "bundle": str(bundle) if keep else "",
            "gates": gates,
            "failed_gates": sorted(failures),
        }
    finally:
        if not keep:
            shutil.rmtree(holder, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the signer's release gates locally inside a real bundle.")
    parser.add_argument("--json", action="store_true", help="machine-readable result")
    parser.add_argument("--keep", action="store_true", help="keep the assembled bundle")
    args = parser.parse_args()

    result = check(keep=args.keep)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1

    print(f"bundle files: {result['files']}")
    for name, rows in result["gates"].items():
        print(f"{'OK  ' if not rows else 'FAIL'} {name}")
        for row in rows[:20]:
            print(f"      {row}")
    if result["bundle"]:
        print(f"bundle kept at: {result['bundle']}")
    print("PRE-RELEASE PASS" if result["ok"] else "PRE-RELEASE FAIL")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
