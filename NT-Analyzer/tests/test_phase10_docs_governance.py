"""Phase 10 — Documentation reorganization + governance amendment workflow.

Covers the Phase 10 acceptance criteria and invariants:
- the canonical docs tree + migration map exist and are separated;
- the markdown link audit passes (no broken relative links);
- global governance mutations require the owner or an explicit
  ``docs.manage_global`` grant (owner-only by default);
- a workspace / strategy override can never mutate global governance;
- the governance amendment journal records the required fields.

No real network, secret or Production access occurs.
"""
from __future__ import annotations

import inspect
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import dev_service_accounts, governance, jobqueue, permissions, server  # noqa: E402

DOCS = ROOT / "docs"


# --------------------------------------------------------------------------- #
# Canonical docs tree + migration map.
# --------------------------------------------------------------------------- #
def test_canonical_docs_tree_exists():
    for name in (
        "current", "architecture", "operations", "security", "product",
        "agents", "strategies", "governance", "changelog", "adr", "archive",
    ):
        assert (DOCS / name).is_dir(), f"missing canonical docs dir: {name}"
    assert (DOCS / "archive" / "audits").is_dir()
    assert (DOCS / "DOCS_STRUCTURE.md").is_file()


def test_new_canonical_dirs_have_index_readme():
    for name in ("security", "product", "agents", "strategies", "changelog", "archive"):
        assert (DOCS / name / "README.md").is_file(), f"missing README for docs/{name}"


def test_docs_structure_map_covers_categories_and_archive():
    text = (DOCS / "DOCS_STRUCTURE.md").read_text(encoding="utf-8")
    for token in ("docs/archive/", "docs/agents/", "docs/strategies/",
                  "docs/security/", "docs/product/", "docs/changelog/",
                  "migration map", "docs.manage_global"):
        assert token in text, f"migration map missing: {token}"


# --------------------------------------------------------------------------- #
# Markdown link audit (no broken relative links).
# --------------------------------------------------------------------------- #
def test_markdown_links_resolve():
    from tools import release_static_scan

    broken = release_static_scan.scan_markdown_links()
    assert broken == [], "broken markdown links: " + "; ".join(broken)


# --------------------------------------------------------------------------- #
# Governance amendment workflow — owner-only (docs.manage_global) writes.
# --------------------------------------------------------------------------- #
def test_owner_resolves_docs_manage_global():
    caps = permissions.resolve_admin_capabilities({"is_owner": True})
    assert caps["docs.manage_global"] is True


def test_plain_user_lacks_docs_manage_global():
    caps = permissions.resolve_admin_capabilities({"is_owner": False})
    assert caps.get("docs.manage_global") is False


def test_delegated_grant_enables_docs_manage_global():
    user = {
        "is_owner": False,
        "admin_permission_grants": {
            "docs.manage_global": {
                "enabled": True, "granted_at_utc": "2026-01-01T00:00:00Z",
                "expires_at_utc": "", "granted_by": "owner",
            }
        },
    }
    caps = permissions.resolve_admin_capabilities(user)
    assert caps["docs.manage_global"] is True


def test_governance_write_requires_manage_capability_is_wired():
    source = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    # The write handler must gate on the manage capability before any mutation.
    idx_post = source.index("def _governance_post(")
    body = source[idx_post: idx_post + 400]
    assert "_require_governance_manage()" in body, "governance writes must gate on manage capability"
    idx_guard = source.index("def _require_governance_manage(")
    guard = source[idx_guard: idx_guard + 1200]
    assert "docs.manage_global" in guard
    assert "is_owner" in guard
    assert "governance_manage_required" in guard


# --------------------------------------------------------------------------- #
# Strategy / workspace override can never mutate global governance.
# --------------------------------------------------------------------------- #
def test_governance_update_functions_have_no_workspace_scope():
    for fn in (governance.update_law, governance.update_markdown_document):
        params = set(inspect.signature(fn).parameters)
        assert not (params & {"workspace", "workspace_id", "tenant", "scope"}), (
            f"{fn.__name__} must not accept a workspace/tenant/scope parameter"
        )


def test_strategy_update_allowlist_excludes_governance():
    source = inspect.getsource(jobqueue.update_strategy_profile)
    # The strict field allowlist must not include any governance/law/document key.
    assert "allowed = {" in source
    for forbidden in ("law", "laws", "governance", "runtime_default",
                      "safety", "document", "capability"):
        assert f'"{forbidden}"' not in source, f"strategy allowlist leaks {forbidden}"
    # And the function must never call into the governance mutation API.
    assert "governance.update" not in source


def test_governance_and_profile_stores_are_disjoint():
    gov_dir = str(governance.data_dir()).replace("\\", "/")
    assert "governance" in gov_dir
    laws = str(governance.laws_path()).replace("\\", "/")
    assert laws.endswith("governance/laws.json")
    # Strategy profiles live in a different store entirely.
    assert "profiles" not in gov_dir


# --------------------------------------------------------------------------- #
# Amendment journal records the required fields.
# --------------------------------------------------------------------------- #
def test_amendment_change_log_records_required_fields():
    previous_root = os.environ.get("NT_ANALYZER_ROOT")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "NT-Analyzer"
        (root / "app").mkdir(parents=True, exist_ok=True)
        os.environ["NT_ANALYZER_ROOT"] = str(root)
        try:
            governance.ensure_governance_files(render=True)
            governance.update_law(
                "GOV-RISK-001",
                {"value": "10000", "reason": "phase 10 amendment test"},
                actor="GitHub Copilot по запросу owner",
            )
            entries = governance.read_change_log(5)
            assert entries, "amendment must be journaled"
            top = entries[0]
            for field in ("actor", "reason", "ts_utc", "amendment_no", "changes"):
                assert field in top, f"amendment missing field: {field}"
            assert top["actor"] == "GitHub Copilot по запросу owner"
            assert str(top["ts_utc"]).endswith("Z")
            assert int(top["amendment_no"]) >= 1
        finally:
            if previous_root is None:
                os.environ.pop("NT_ANALYZER_ROOT", None)
            else:
                os.environ["NT_ANALYZER_ROOT"] = previous_root


def test_compact_document_change_keeps_full_diff_in_details():
    before = "# Risk\n\n- Max drawdown: 15%\n- Stable: yes\n"
    after = "# Risk\n\n- Max drawdown: 10%\n- Stable: yes\n"
    change = governance._document_change_row(before, after)[0]
    assert change["before_text"] == "- Max drawdown: 15%"
    assert change["after_text"] == "- Max drawdown: 10%"
    assert {row["op"] for row in change["diff"]} >= {"del", "add"}


def test_revision_one_uses_factual_creation_metadata():
    revision = governance.document_revisions("legal-00")["revisions"][0]
    assert revision["revision_no"] == 1
    assert revision["title"] == "документ создан"
    assert revision["ts_utc"] == "2026-08-10T20:49:49Z"
    assert revision["author_kind"] == "ai"
    assert "Claude Opus 4.8" in revision["author"]
    assert revision["initiator"] == governance.PROJECT_OWNER


def test_public_document_view_hides_owner_paths_and_internal_provenance():
    charter = governance.read_document("charter")
    assert charter and "STRATFORGE_INTERNAL_AMENDMENT" in charter["content"]
    public = governance.public_document(charter)
    assert "owner" not in public
    assert "abs_path" not in public and "rel_path" not in public
    assert "STRATFORGE_INTERNAL_AMENDMENT" not in public["content"]
    roles = next(row for row in governance.list_documents() if row["id"] == "roles")
    assert governance.document_is_public(roles) is False


def test_authenticated_governance_author_cannot_be_overridden_by_request_body():
    handler = object.__new__(server.Handler)
    uid = dev_service_accounts.SERVICE_ACCOUNTS["gpt"]["uid"]
    handler._remote_context = {
        "source": "dev_service", "service_actor": "gpt", "user_id": uid,
        "is_owner": True, "user": {"is_service_account": True},
    }
    identity = handler._governance_actor()
    assert identity["author"] == dev_service_accounts.SERVICE_ACCOUNTS["gpt"]["label"]
    assert identity["author_id"] == "service:gpt"
    assert identity["initiator"] == governance.PROJECT_OWNER
    source = inspect.getsource(server.Handler._governance_actor)
    assert '.get("agent")' not in source
    assert '.get("initiator")' not in source
