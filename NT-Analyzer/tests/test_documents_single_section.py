"""Documents is one section, not two sibling menu entries.

Global governance documents and workspace specifications are two scopes of the
same thing. As separate entries the reader had to decide which one held the
document they wanted before opening either, and an operator holding only one of
the two capabilities still saw both -- the second opening onto a permission
error, which reads as a fault rather than as a boundary.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
UI = (ROOT / "app" / "static" / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")


def _modules() -> str:
    start = SERVER.index("_ADMIN_MODULES")
    return SERVER[start:SERVER.index("\n)", start)]


def test_there_is_exactly_one_documents_module():
    modules = _modules()
    ids = re.findall(r'"id": "([a-z-]+)"[^}]*"group": "Документы"', modules)
    assert ids == ["docs"], f"expected a single Documents module, found {ids}"


def test_the_old_split_modules_are_gone():
    modules = _modules()
    assert '"id": "docs-global"' not in modules
    assert '"id": "docs-workspace"' not in modules


def test_the_section_is_reachable_by_anyone_who_can_open_the_panel():
    """Gated on admin.view, with each scope inside gated on its own capability.
    An entry whose only outcome is a permission error is worse than no entry."""
    modules = _modules()
    entry = next(line for line in modules.splitlines() if '"id": "docs"' in line)
    assert '"capability": "admin.view"' in entry


def test_both_scopes_are_still_rendered():
    assert "renderAdminDocumentsInto" in UI
    assert "renderAdminDocsGlobalInto" in UI
    assert "renderAdminDocsWorkspaceInto" in UI


def test_each_scope_is_gated_on_its_own_capability():
    section = UI[UI.index("async function renderAdminDocumentsInto"):]
    section = section[:section.index("async function renderAdminDocsGlobalInto")]
    assert "docs.manage_global" in section
    assert "docs.manage_workspace" in section
    assert "strategy.spec.manage" in section


def test_a_caller_with_no_documents_capability_is_told_why():
    section = UI[UI.index("async function renderAdminDocumentsInto"):]
    section = section[:section.index("async function renderAdminDocsGlobalInto")]
    assert "Нет прав на управление документами" in section


def test_the_old_module_ids_still_route():
    """An existing deep link should land in the section rather than on an empty
    panel."""
    assert "moduleId === 'docs-global'" in UI
    assert "moduleId === 'docs-workspace'" in UI
    assert "renderAdminDocumentsInto(node, 'global')" in UI
    assert "renderAdminDocumentsInto(node, 'workspace')" in UI


def test_the_section_states_the_boundary_between_the_scopes():
    section = UI[UI.index("async function renderAdminDocumentsInto"):]
    section = section[:section.index("async function renderAdminDocsGlobalInto")]
    assert "не может изменить governance-документ" in section
