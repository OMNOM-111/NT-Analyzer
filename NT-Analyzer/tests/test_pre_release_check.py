"""The local pre-release gate must mean what it says.

A PASS here is a claim that the same gates pass on the signing/build node. The
tests that matter are therefore the ones that reproduce the two failures which
actually reached the signer, so the gate cannot quietly stop catching them.
"""
from __future__ import annotations

import json
import shutil

import pytest

from tools import pre_release_check, release_bundle


@pytest.fixture()
def repo(tmp_path):
    """A miniature repository with the shape the checks care about."""
    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    (root / "docs" / "changelog").mkdir(parents=True)
    (root / "docs" / "current").mkdir(parents=True)
    (root / "app").mkdir()
    shutil.copy2(release_bundle.ROOT / "tools" / "release_static_scan.py",
                 root / "tools" / "release_static_scan.py")
    (root / "app" / "server.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "VERSION.json").write_text(
        json.dumps({"version": "0.10.0-beta.81"}), encoding="utf-8")
    (root / "docs" / "current" / "HANDOFF.md").write_text("# Handoff\n", encoding="utf-8")
    (root / "docs" / "changelog" / "2026-08-31-beta81-x.md").write_text(
        "# beta.81 — тема\n\n- Пункт.\n", encoding="utf-8")
    return root


def test_selection_is_shared_with_the_builder() -> None:
    """One list, or the local check and the signer drift apart again."""
    import importlib.util

    spec = importlib.util.find_spec("tools.build_server_release")
    assert spec is not None
    source = (release_bundle.ROOT / "tools" / "build_server_release.py").read_text(
        encoding="utf-8")
    assert "from tools.release_bundle import" in source
    assert "_INCLUDED_TREES = (" not in source, "the builder must not keep its own copy"


def test_release_bundle_has_no_signing_dependency() -> None:
    """The check must run on a machine with no release key and no cryptography."""
    import ast

    source = (release_bundle.ROOT / "tools" / "release_bundle.py").read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "cryptography" not in imported


def test_pass_on_the_real_repository() -> None:
    result = pre_release_check.check()
    assert result["ok"], result["failed_gates"]
    assert result["files"] > 0


def test_catches_a_link_that_leaves_the_bundle(repo, monkeypatch) -> None:
    """The beta.81 signer failure, reproduced locally.

    The link resolves in the repository and not in the bundle, which is exactly
    why running the scan from a checkout reported PASS.
    """
    entry = repo / "docs" / "changelog" / "2026-08-31-beta81-x.md"
    entry.write_text("# beta.81 — тема\n\n- Пункт.\n\n[H](../current/HANDOFF.md)\n",
                     encoding="utf-8")
    assert (repo / "docs" / "current" / "HANDOFF.md").exists()

    monkeypatch.setattr(release_bundle, "_selected_files", lambda root: [
        p.relative_to(repo) for p in sorted(repo.rglob("*"))
        if p.is_file() and "current" not in p.parts
    ])
    monkeypatch.setattr(pre_release_check, "_selected_files",
                        release_bundle._selected_files)
    monkeypatch.setattr(pre_release_check, "_check_runtime_reads",
                        lambda bundle, shipped: [])

    result = pre_release_check.check(repo)
    assert result["ok"] is False
    assert "static_scan_in_bundle" in result["failed_gates"]
    assert any("HANDOFF" in row for row in result["gates"]["static_scan_in_bundle"])


def test_catches_a_runtime_read_that_is_not_shipped() -> None:
    """The beta.80 defect: the legal package the registration screen serves."""
    from app import governance

    shipped = {
        row["path"] for row in governance.DEFAULT_DOCUMENTS["documents"]
        if str(row.get("path") or "") and not str(row.get("path")).startswith("docs/legal/")
    }
    errors = pre_release_check._check_runtime_reads(
        release_bundle.ROOT, shipped)
    assert any("docs/legal/" in row for row in errors)
    assert any("not shipped" in row for row in errors)


def test_catches_a_summary_that_cannot_resolve_inside_the_bundle(tmp_path) -> None:
    """The beta.81 empty «Что изменилось»: changelog absent from the artifact."""
    bundle = tmp_path / "bundle"
    (bundle / "docs" / "changelog").mkdir(parents=True)
    (bundle / "VERSION.json").write_text(
        json.dumps({"version": "0.10.0-beta.81"}), encoding="utf-8")

    from app import governance

    shipped = {
        str(row.get("path") or "") for row in governance.DEFAULT_DOCUMENTS["documents"]
    }
    errors = pre_release_check._check_runtime_reads(bundle, shipped)
    assert any("release summary" in row and "0.10.0-beta.81" in row for row in errors)


def test_materialise_copies_exactly_the_shipped_files(tmp_path) -> None:
    destination = tmp_path / "bundle"
    destination.mkdir()
    selected = pre_release_check.materialise(release_bundle.ROOT, destination)
    copied = {p.relative_to(destination).as_posix()
              for p in destination.rglob("*") if p.is_file()}
    assert copied == {path.as_posix() for path in selected}
    # The owner-only configuration must not appear in an assembled bundle.
    assert "docs/legal/OWNER_LEGAL_CONFIGURATION.md" not in copied
