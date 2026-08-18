"""Documents is one surface, and it is not in Admin.

Global governance documents and workspace specifications are two scopes of the
same thing. They were first two Admin entries, then one; both arrangements left
half of "the documents" behind an operator panel while the rest sat in the main
menu, so nobody could answer "where are the documents" without first knowing
which kind they meant.

Documents are not an operator tool. They now live in one place a member can
reach from the main menu, with the workspace scope appearing only for callers
who may manage it.
"""
from __future__ import annotations

from pathlib import Path

from app import server as server_mod

ROOT = Path(__file__).resolve().parents[1]
AURORA = ROOT / "app" / "static" / "aurora"
UI = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
PAGE = (AURORA / "assets" / "pages" / "documents.js").read_text(encoding="utf-8")
HTML = (AURORA / "documents.html").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Documents left Admin.
# --------------------------------------------------------------------------- #
def test_admin_offers_no_documents_module():
    ids = {m["id"] for m in server_mod._ADMIN_MODULES}
    assert "docs" not in ids
    assert "docs-global" not in ids
    assert "docs-workspace" not in ids


def test_no_admin_group_is_named_documents():
    groups = {m.get("group") for m in server_mod._ADMIN_MODULES}
    assert "Документы" not in groups


def test_the_old_admin_ids_point_at_the_documents_page():
    """A deep link into the retired module should say where documents went
    rather than render an empty panel."""
    assert "'docs', 'docs-global', 'docs-workspace'" in UI
    section = UI[UI.index("'docs', 'docs-global', 'docs-workspace'"):]
    section = section[:section.index("return;")]
    assert 'href="documents.html"' in section


def test_the_admin_document_renderers_are_gone():
    for name in ("renderAdminDocumentsInto", "renderAdminDocsGlobalInto",
                 "renderAdminDocsWorkspaceInto", "openGovernanceDoc"):
        assert name not in UI, name


# --------------------------------------------------------------------------- #
# One surface in the main menu, holding both scopes.
# --------------------------------------------------------------------------- #
def test_documents_is_in_the_main_navigation():
    assert "{ id: 'docs', label: 'Документы', href: 'documents.html'" in UI


def test_the_page_carries_both_scopes():
    assert 'data-docs-scope="governance"' in HTML
    assert 'data-docs-scope="workspace"' in HTML
    assert "renderWorkspaceDocs" in PAGE


def test_the_workspace_scope_is_offered_only_to_callers_who_may_manage_it():
    """A tab whose only outcome is a permission error reads as a fault rather
    than as a boundary."""
    section = PAGE[PAGE.index("function wireDocumentScopes"):]
    section = section[:section.index("\n  }\n")]
    assert "canWorkspace" in section
    assert "tabs.hidden = true" in section
    assert "docs.manage_workspace" in PAGE
    assert "strategy.spec.manage" in PAGE


def test_the_page_states_the_boundary_between_the_scopes():
    assert "governance-документы и safety-limits" in PAGE


def test_the_workspace_scope_loads_only_when_opened():
    """Most visits never leave the governance scope, and the workspace list
    costs a request."""
    section = PAGE[PAGE.index("function wireDocumentScopes"):]
    assert "loaded" in section[:section.index("\n  }\n")]


def test_the_workspace_scope_keeps_the_full_revision_workflow():
    for action in ("submit", "approve", "publish"):
        assert '"%s"' % action in PAGE or "'%s'" % action in PAGE
    assert "documentRevisionAction" in PAGE
    assert "documentRevert" in PAGE
    assert "documentRevise" in PAGE
