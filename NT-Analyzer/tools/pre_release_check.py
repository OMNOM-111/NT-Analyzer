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
    """Files the running service reads, which have to travel with it.

    Every escape so far was of this kind: the legal package the registration
    screen serves, and the changelog the release summary reads. Neither is
    imported, so nothing failed until a deployed environment tried to read it
    and served an empty page.

    A document whose path leaves the shipment root cannot ship at all; those
    are reported as accepted exclusions rather than failures, because no change
    to the file selection could satisfy them.
    """
    errors: list[str] = []
    sys.path.insert(0, str(ROOT))
    try:
        from app import governance, release_summary
    except Exception as exc:  # pragma: no cover - import guard
        return [f"cannot inspect runtime reads: {type(exc).__name__}: {exc}"]

    for row in governance.DEFAULT_DOCUMENTS["documents"]:
        path = str(row.get("path") or "")
        if not path or not governance.document_is_public(row):
            continue
        if path.startswith("..") or Path(path).is_absolute():
            continue                      # outside the shipment root by design
        if not (ROOT / path).is_file():
            continue                      # absent from the repository too
        if path not in shipped:
            errors.append(
                f"public document {row.get('id')} is not shipped: {path} "
                "(the Documents API would serve it empty)")

    version = ""
    version_file = bundle / "VERSION.json"
    if version_file.is_file():
        try:
            version = str(json.loads(version_file.read_text(encoding="utf-8")).get("version") or "")
        except ValueError:
            errors.append("VERSION.json in the artifact is not valid JSON")
    if version:
        # Resolved against the bundle, not the repository.
        summary = release_summary.summary_for(
            version, directory=bundle / "docs" / "changelog")
        if not summary["title"]:
            errors.append(
                f"release summary for {version} does not resolve inside the artifact; "
                "the card would show no «Что изменилось»")
    return errors


def accepted_exclusions() -> list[str]:
    """Registry documents that can never ship, stated rather than hidden."""
    sys.path.insert(0, str(ROOT))
    try:
        from app import governance
    except Exception:  # pragma: no cover - import guard
        return []
    rows = []
    for row in governance.DEFAULT_DOCUMENTS["documents"]:
        path = str(row.get("path") or "")
        if path.startswith("..") or (path and Path(path).is_absolute()):
            rows.append(f"{row.get('id')} -> {path}")
    return rows


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


def _check_javascript_syntax(bundle: Path) -> list[str]:
    """The shipped front-end has to parse.

    A literal newline inside a string shipped once and was caught only on the
    Windows CI runner, because nothing local looked at the JavaScript at all.
    """
    scripts = sorted(bundle.glob("app/static/aurora/assets/*.js"))
    if not scripts:
        return ["no Aurora assets in the artifact"]
    errors: list[str] = []
    for script in scripts:
        completed = subprocess.run(
            ["node", "--check", str(script)], cwd=bundle, text=True,
            encoding="utf-8", errors="replace", capture_output=True,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()
            first = next((line for line in detail if "Error" in line), "")
            errors.append(f"{script.relative_to(bundle).as_posix()}: {first or 'parse failed'}")
    return errors


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
            "javascript_syntax": _check_javascript_syntax(bundle),
        }
        failures = {name: rows for name, rows in gates.items() if rows}
        return {
            "ok": not failures,
            "files": len(selected),
            "bundle": str(bundle) if keep else "",
            "gates": gates,
            "failed_gates": sorted(failures),
            "accepted_exclusions": accepted_exclusions(),
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
    for row in result.get("accepted_exclusions") or []:
        print(f"     accepted exclusion: {row}")
    if result["bundle"]:
        print(f"bundle kept at: {result['bundle']}")
    print("PRE-RELEASE PASS" if result["ok"] else "PRE-RELEASE FAIL")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
