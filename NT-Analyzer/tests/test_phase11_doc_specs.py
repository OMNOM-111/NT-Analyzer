"""Phase 11 — workspace / strategy document specification revisions.

Exercises the ``app.doc_specs`` control plane directly (no network, secret or
Production access). Covers the acceptance invariants from the audit finding:

- the draft -> review -> approved -> published lifecycle, supersede + revert;
- workspace / strategy scope isolation (a member can only touch their own
  workspace and can never create a global / governance document);
- ``strategy.spec.manage`` gating for non-owners;
- the module never reads or mutates the governance store (global governance /
  safety limits stay in a separate control plane);
- migration 0011 is additive (expand-only) and RLS-scoped.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import account_auth, doc_specs  # noqa: E402

OWNER = {"user_id": 999, "is_owner": True}
MEMBER = {"user_id": 7, "is_owner": False}
SPEC_CAPS = {"strategy.spec.manage": True}
GLOBAL_CAPS = {"docs.manage_global": True}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.delenv("STRATFORGE_ENV", raising=False)
    monkeypatch.setattr(doc_specs, "_store_path", lambda: tmp_path / "doc_specs.dpapi")
    monkeypatch.setattr(doc_specs, "_audit_path", lambda: tmp_path / "doc-specs-audit.jsonl")
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    for mod in (doc_specs.secure_store, account_auth.secure_store):
        monkeypatch.setattr(mod, "_protect", lambda b: b)
        monkeypatch.setattr(mod, "_unprotect", lambda b: b)
        monkeypatch.setattr(mod, "available", lambda: True)
    return tmp_path


# --------------------------------------------------------------------------- #
# Lifecycle: create -> submit -> approve -> publish -> supersede -> revert.
# --------------------------------------------------------------------------- #
def test_full_lifecycle_supersede_and_revert(store):
    created = doc_specs.create_document(
        actor=OWNER, scope_type="global", slug="release-notes",
        title="Release notes", content={"body": "v1"}, reason="init",
    )
    doc_id = created["document"]["document_id"]
    rev1 = created["revision"]["revision_id"]
    assert created["revision"]["status"] == "draft"

    doc_specs.submit_revision(actor=OWNER, revision_id=rev1)
    doc_specs.approve_revision(actor=OWNER, revision_id=rev1)
    published = doc_specs.publish_revision(actor=OWNER, revision_id=rev1)
    assert published["revision"]["status"] == "published"

    detail = doc_specs.get_document(actor=OWNER, document_id=doc_id)
    assert detail["document"]["current_revision_id"] == rev1
    assert detail["document"]["published_revision"] == 1

    # A second published revision supersedes the first and becomes current.
    r2 = doc_specs.create_revision(actor=OWNER, document_id=doc_id, content={"body": "v2"})
    rev2 = r2["revision"]["revision_id"]
    doc_specs.submit_revision(actor=OWNER, revision_id=rev2)
    doc_specs.approve_revision(actor=OWNER, revision_id=rev2)
    doc_specs.publish_revision(actor=OWNER, revision_id=rev2)

    detail = doc_specs.get_document(actor=OWNER, document_id=doc_id)
    by_rev = {r["revision"]: r for r in detail["revisions"]}
    assert by_rev[1]["status"] == "superseded"
    assert by_rev[2]["status"] == "published"
    assert detail["document"]["current_revision_id"] == rev2

    # Revert clones an earlier revision's content into a NEW draft (history intact).
    reverted = doc_specs.revert_document(actor=OWNER, document_id=doc_id, to_revision=1,
                                         reason="rollback")
    assert reverted["revision"]["status"] == "draft"
    assert reverted["revision"]["revision"] == 3
    assert reverted["revision"]["reverted_from_revision"] == 1
    detail = doc_specs.get_document(actor=OWNER, document_id=doc_id)
    assert {r["content"].get("body") for r in detail["revisions"]} == {"v1", "v2"}


def test_invalid_transition_and_open_revision_guards(store):
    created = doc_specs.create_document(actor=OWNER, scope_type="global", slug="doc-a")
    doc_id = created["document"]["document_id"]
    rev = created["revision"]["revision_id"]
    # draft -> approved is not a legal transition (must pass through review).
    with pytest.raises(doc_specs.DocSpecError) as exc:
        doc_specs.approve_revision(actor=OWNER, revision_id=rev)
    assert exc.value.code == "invalid_transition"
    # A second open revision is refused while one is still open.
    with pytest.raises(doc_specs.DocSpecError) as exc2:
        doc_specs.create_revision(actor=OWNER, document_id=doc_id, content={})
    assert exc2.value.code == "open_revision_exists"


def test_slug_and_scope_validation(store):
    with pytest.raises(doc_specs.DocSpecError) as bad_slug:
        doc_specs.create_document(actor=OWNER, scope_type="global", slug="Bad Slug!")
    assert bad_slug.value.code == "slug_invalid"
    with pytest.raises(doc_specs.DocSpecError) as bad_scope:
        doc_specs.create_document(actor=OWNER, scope_type="planet", slug="x")
    assert bad_scope.value.code == "scope_invalid"


# --------------------------------------------------------------------------- #
# Scope isolation + permission gating.
# --------------------------------------------------------------------------- #
def test_workspace_member_scoped_to_own_workspace(store):
    ok = doc_specs.create_document(
        actor=MEMBER, scope_type="workspace", slug="playbook",
        workspace_id="ws_a", admin_caps=SPEC_CAPS, actor_workspace_id="ws_a",
    )
    assert ok["document"]["workspace_id"] == "ws_a"

    # Same member cannot create in another workspace.
    with pytest.raises(doc_specs.DocSpecError) as cross:
        doc_specs.create_document(
            actor=MEMBER, scope_type="workspace", slug="playbook2",
            workspace_id="ws_b", admin_caps=SPEC_CAPS, actor_workspace_id="ws_a",
        )
    assert cross.value.code == "cross_workspace_forbidden"


def test_workspace_member_cannot_create_global_governance(store):
    for scope in ("global", "governance", "changelog"):
        with pytest.raises(doc_specs.DocSpecError) as exc:
            doc_specs.create_document(
                actor=MEMBER, scope_type=scope, slug="x-" + scope,
                admin_caps=SPEC_CAPS, actor_workspace_id="ws_a",
            )
        assert exc.value.code == "global_scope_forbidden"


def test_non_owner_without_capability_is_forbidden(store):
    with pytest.raises(doc_specs.DocSpecError) as exc:
        doc_specs.create_document(
            actor=MEMBER, scope_type="workspace", slug="p",
            workspace_id="ws_a", admin_caps={}, actor_workspace_id="ws_a",
        )
    assert exc.value.code == "strategy_spec_forbidden"


def test_docs_manage_global_grant_enables_global_scope(store):
    ok = doc_specs.create_document(
        actor=MEMBER, scope_type="global", slug="notes", admin_caps=GLOBAL_CAPS,
    )
    assert ok["document"]["scope_type"] == "global"


def test_member_list_only_sees_own_workspace(store):
    doc_specs.create_document(actor=OWNER, scope_type="workspace", slug="a",
                              workspace_id="ws_a")
    doc_specs.create_document(actor=OWNER, scope_type="workspace", slug="b",
                              workspace_id="ws_b")
    doc_specs.create_document(actor=OWNER, scope_type="global", slug="g")
    listed = doc_specs.list_documents(actor=MEMBER, admin_caps=SPEC_CAPS,
                                      actor_workspace_id="ws_a")
    workspaces = {d["workspace_id"] for d in listed["documents"]}
    scopes = {d["scope_type"] for d in listed["documents"]}
    assert workspaces == {"ws_a"}
    assert "global" not in scopes


# --------------------------------------------------------------------------- #
# The module never touches the governance store / safety limits.
# --------------------------------------------------------------------------- #
def test_doc_specs_does_not_import_or_mutate_governance():
    source = inspect.getsource(doc_specs)
    assert "import governance" not in source
    assert "governance.update" not in source
    assert "safety_limit" not in source


def test_doc_spec_store_is_disjoint_from_governance(store):
    from app import governance
    spec_path = str(doc_specs._store_path()).replace("\\", "/")
    laws_path = str(governance.laws_path()).replace("\\", "/")
    assert "governance" not in spec_path
    assert spec_path != laws_path
    # Creating a spec must not create or touch the governance laws file.
    doc_specs.create_document(actor=OWNER, scope_type="workspace", slug="s",
                              workspace_id="ws_a")
    assert not (store / "governance" / "laws.json").exists()


# --------------------------------------------------------------------------- #
# Migration 0011 is additive + RLS-scoped and discovered by the runner.
# --------------------------------------------------------------------------- #
def test_migration_0011_is_additive_and_rls_scoped():
    sql_path = (ROOT / "app" / "production_storage" / "migrations"
                / "0011_document_specifications.sql")
    sql = sql_path.read_text(encoding="utf-8").lower()
    assert "create table if not exists sf_documents" in sql
    assert "create table if not exists sf_document_revisions" in sql
    assert "references sf_users(user_uuid)" in sql
    assert "enable row level security" in sql
    assert "sf_scope_global()" in sql
    assert "sf_scope_workspace()" in sql
    # Expand-only: no destructive statements against existing data.
    assert "drop table" not in sql
    assert "drop column" not in sql
    assert "delete from" not in sql


def test_migration_runner_discovers_0011():
    from app.production_storage.core import MigrationRunner

    versions = [row["version"] for row in MigrationRunner.migrations()]
    assert versions == list(range(1, len(versions) + 1))
    assert 11 in versions
