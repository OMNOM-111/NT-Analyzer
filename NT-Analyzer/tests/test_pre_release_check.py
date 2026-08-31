"""The local pre-release gate has to mean what it says.

A PASS here is a claim that the same gates pass on the signing/build node, so
the tests that matter are the ones reproducing failures that actually reached
it: a runtime file left out of the shipment, a markdown link that resolves in
the repository and not in the bundle, and code that does not parse.
"""
from __future__ import annotations

import json
import shutil

import pytest

from tools import pre_release_check, release_bundle


@pytest.fixture()
def bundle(tmp_path):
    """The real shipment, assembled once for the checks that read it."""
    destination = tmp_path / "bundle"
    destination.mkdir()
    pre_release_check.materialise(release_bundle.ROOT, destination)
    return destination


# --------------------------------------------------------------------------- #
# One selection, shared with the builder.
# --------------------------------------------------------------------------- #
def test_selection_is_shared_with_the_builder() -> None:
    """One list, or the local check and the signer drift apart again."""
    source = (release_bundle.ROOT / "tools" / "build_server_release.py").read_text(
        encoding="utf-8")
    assert "from tools.release_bundle import" in source
    assert "_INCLUDED_TREES = (" not in source, "the builder must not keep its own copy"
    assert "_INCLUDED_FILES = (" not in source
    assert "_EXCLUDED_FILES = {" not in source


def test_release_bundle_has_no_signing_dependency() -> None:
    """The check must run on a machine with no release key installed."""
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
    assert set(result["gates"]) == {
        "static_scan_in_bundle", "runtime_reads_shipped",
        "python_compiles", "javascript_syntax",
    }


# --------------------------------------------------------------------------- #
# The failures that reached the signer.
# --------------------------------------------------------------------------- #
def test_catches_a_public_document_left_out_of_the_shipment(monkeypatch) -> None:
    """The beta.80 class: docs/legal was not shipped and served empty pages."""
    shipped = {path.as_posix() for path in release_bundle._selected_files(release_bundle.ROOT)}
    without_legal = {row for row in shipped if not row.startswith("docs/legal/")}
    errors = pre_release_check._check_runtime_reads(
        release_bundle.ROOT, without_legal)
    assert any("docs/legal/" in row for row in errors)
    assert any("is not shipped" in row for row in errors)


def test_catches_a_link_that_leaves_the_bundle(bundle) -> None:
    """The beta.81 signer failure, reproduced against the real shipment.

    The target exists in the repository and not in the bundle, which is exactly
    why running the scan from a checkout reported PASS while the signer, which
    runs it inside the bundle, refused the build.
    """
    outside = "docs/current/CLEAN_CLOSEOUT_HANDOFF.md"
    assert (release_bundle.ROOT / outside).is_file(), "target must exist in the repo"
    assert not (bundle / outside).is_file(), "and must not be in the shipment"

    entry = next(iter(sorted((bundle / "docs" / "changelog").glob("*.md"))))
    entry.write_text(
        entry.read_text(encoding="utf-8") + "\n[H](../current/CLEAN_CLOSEOUT_HANDOFF.md)\n",
        encoding="utf-8")

    errors = pre_release_check._run_static_scan(bundle)
    assert errors
    assert any("CLEAN_CLOSEOUT_HANDOFF" in row for row in errors)


def test_catches_javascript_that_does_not_parse(bundle) -> None:
    """The beta.81 class: a literal newline in a string, caught only on CI."""
    target = bundle / "app" / "static" / "aurora" / "assets" / "api.js"
    assert target.is_file()
    target.write_text(target.read_text(encoding="utf-8") + '\nconst broken = "x\n',
                      encoding="utf-8")
    errors = pre_release_check._check_javascript_syntax(bundle)
    assert any("api.js" in row for row in errors)


def test_catches_python_that_does_not_compile(bundle) -> None:
    (bundle / "app" / "_broken_probe.py").write_text("def (:\n", encoding="utf-8")
    assert pre_release_check._check_python_compiles(bundle)


def test_catches_a_summary_that_cannot_resolve_inside_the_bundle(tmp_path) -> None:
    """The beta.81 empty «Что изменилось»: changelog absent from the artifact."""
    empty = tmp_path / "bundle"
    (empty / "docs" / "changelog").mkdir(parents=True)
    (empty / "VERSION.json").write_text(json.dumps({"version": "0.10.0-beta.83"}),
                                        encoding="utf-8")
    shipped = {path.as_posix() for path in release_bundle._selected_files(release_bundle.ROOT)}
    errors = pre_release_check._check_runtime_reads(empty, shipped)
    assert any("release summary" in row and "0.10.0-beta.83" in row for row in errors)


# --------------------------------------------------------------------------- #
# What the shipment contains.
# --------------------------------------------------------------------------- #
def test_materialise_copies_exactly_the_shipped_files(tmp_path) -> None:
    destination = tmp_path / "bundle"
    destination.mkdir()
    selected = pre_release_check.materialise(release_bundle.ROOT, destination)
    copied = {path.relative_to(destination).as_posix()
              for path in destination.rglob("*") if path.is_file()}
    assert copied == {path.as_posix() for path in selected}
    assert "docs/legal/OWNER_LEGAL_CONFIGURATION.md" not in copied
    assert "docs/agents/AGENTS.md" not in copied


def test_public_agent_documents_are_shipped(bundle) -> None:
    """Listed with audience "user" and served by the Documents API: an artifact
    without them opened an empty page, which is the docs/legal failure again."""
    for name in ("AI_LAB_CLOUD_AGENTS.md", "AI_LAB_COMPETITIVE_FEEDBACK.md"):
        target = bundle / "docs" / "agents" / name
        assert target.is_file(), f"{name} must travel with the artifact"
        assert target.read_text(encoding="utf-8-sig").strip()


def test_a_public_document_outside_the_shipment_root_is_a_failure() -> None:
    """Being unreachable by any release is a contradiction, not an exemption.

    Four legacy-* documents were advertised to users by the public allowlist
    while living outside the product tree, where no file selection could ever
    include them. They are no longer public; if one were re-advertised, this
    must refuse it rather than record it as accepted.
    """
    from app import governance

    shipped = {path.as_posix() for path in release_bundle._selected_files(release_bundle.ROOT)}
    original = governance.PUBLIC_DOCUMENT_IDS
    governance.PUBLIC_DOCUMENT_IDS = frozenset(set(original) | {"legacy-rules"})
    try:
        errors = pre_release_check._check_runtime_reads(release_bundle.ROOT, shipped)
    finally:
        governance.PUBLIC_DOCUMENT_IDS = original
    assert any("legacy-rules" in row and "outside the shipment root" in row
               for row in errors)
    assert not pre_release_check._check_runtime_reads(release_bundle.ROOT, shipped)


def test_legacy_project_documents_are_not_advertised_to_users() -> None:
    """Owner project-rules material, kept outside the product and superseded."""
    from app import governance

    for doc_id in ("legacy-rules", "legacy-registry", "legacy-hub-deploy",
                   "legacy-family-plan"):
        row = next(r for r in governance.DEFAULT_DOCUMENTS["documents"]
                   if r["id"] == doc_id)
        assert not governance.document_is_public(row), (
            f"{doc_id} is served to users but no release can carry it")
        # Still registered, so the owner reaches it through the privileged path.
        assert row.get("path")
