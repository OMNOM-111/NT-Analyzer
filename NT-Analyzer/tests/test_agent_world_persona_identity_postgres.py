"""NEW optional Persona identity PG invariants; not historical PG evidence.

Reuses only the explicit disposable, loopback, non-BYPASSRLS acceptance fixture.
Missing opt-in skips these cases; SQLite PASS does not certify PostgreSQL.
"""
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.ai_control_center.domain_service import DomainService
from app.ai_control_center.postgres_repository import PostgresAgentWorldRepository
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_domain_service import NOW, act, get, context
from tests.test_agent_world_postgres import database, repo
from tests import test_agent_world_persona_identity as parity


@pytest.fixture
def pg_env(repo):
    admit = lambda: None
    return SimpleNamespace(repo=repo, service=DomainService(repo, now=lambda: NOW),
                           ctx=context(), admit=admit)


@pytest.mark.parametrize("fields,error", [
    ({"main_assistant": True}, "persona_main_already_assigned"),
    ({"aliases": ["Общий"]}, "persona_alias_already_assigned"),
])
def test_actual_pg_serialized_assignment_has_one_winner(pg_env, fields, error):
    parity.test_concurrent_identity_assignment_has_one_winner_in_real_sqlite(pg_env, fields, error)


def test_actual_pg_alias_collisions_respect_private_user_and_workspace_scope(pg_env):
    parity.test_alias_and_name_conflicts_are_private_and_checked_at_activation(pg_env)


def test_actual_pg_main_swap_and_suspended_slot_are_explicit(pg_env):
    parity.test_main_swap_requires_explicit_clear_and_keeps_suspended_slot(pg_env)


def test_actual_pg_same_names_require_uuid_without_history_rewrite(pg_env):
    parity.test_same_display_names_are_not_rewritten_and_uuid_choice_is_unambiguous(pg_env)


def test_actual_pg_foreign_inactive_and_nonhuman_selections_fail_closed(pg_env):
    parity.test_foreign_draft_retired_and_nonhuman_selections_fail_closed(pg_env)


def test_actual_pg_identity_revision_and_visual_voice_survive_restart(pg_env):
    one = parity.active(pg_env, aliases=["Маруся"], main_assistant=True,
                        avatar_key="marina", voice_mode="browser", voice_language="ru-RU")
    changed = act(pg_env, one, action="update", payload={"name": "Марина — новое имя"})["item"]
    restarted = PostgresAgentWorldRepository(pg_env.repo.client, environment=pg_env.repo.environment)
    pg_env.repo = restarted
    pg_env.service = DomainService(restarted, now=lambda: NOW)
    found = parity.resolve(pg_env, "@Маруся: рабочее поручение")
    assert found.persona_id == one["id"] and found.revision == changed["revision"]
    current = get(pg_env, "personas", one["id"])
    for key in ("aliases", "main_assistant", "avatar_key", "voice_mode", "voice_language"):
        assert current[key] == one[key]
    historical = restarted.get_revision(context=pg_env.ctx, kind=EntityKind.PERSONA,
        entity_id=UUID(one["id"]), revision=one["revision"])
    assert historical.display_name == "Марина" and historical.header.entity_id == UUID(one["id"])
    with pytest.raises(ContractError, match="persona_selection_unavailable"):
        parity.resolve(pg_env, "Задание", one["id"], ctx=context(user=2))
