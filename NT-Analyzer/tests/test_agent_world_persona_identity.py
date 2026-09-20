"""Scoped Persona identity; real disposable ledger, no network or owner state."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
import json
from uuid import uuid4

import pytest

from app.ai_control_center import contracts as c, persona_identity as identity
from app.ai_control_center import application_chat, domain_gateway, live_gateway, model_chat
from app.ai_control_center.model_service import ModelService
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_domain_service import env, create, act, get, context
from tests.test_agent_world_models import setup as model_setup, connected


def active(env, name="Марина", key="persona-identity-one", **fields):
    item = create(env, payload={"name": name, **fields}, key=key)["item"]
    return act(env, item)["item"]


def resolve(env, message, persona_id=None, ctx=None):
    service = ModelService(env.repo, admit=lambda *_: env.admit())
    return identity.resolve_chat(service, context=ctx or env.ctx, message=message, persona_id=persona_id)


def test_alias_main_and_old_client_rename_preserve_all_persona_fields(env):
    one = active(env, aliases=["Маруся", "équipe"], main_assistant=True,
                 avatar_key="marina", voice_mode="browser", voice_language="ru-RU")
    revision = one["revision"]
    changed = act(env, one, action="update", payload={"name": "Марина — исследователь"})["item"]
    assert changed["id"] == one["id"] and changed["revision"] == revision + 1
    for key in ("aliases", "main_assistant", "avatar_key", "voice_mode", "voice_language"):
        assert changed[key] == one[key]
    found = resolve(env, "@МАРУСЯ, проверь подключение")
    assert found.persona_id == one["id"] and found.display_name == changed["title"]
    assert found.reason == "address" and found.message == "проверь подключение"
    with pytest.raises(FrozenInstanceError):
        found.persona_id = str(uuid4())
    with env.repo._transaction() as db:
        old = db.execute("SELECT payload FROM aw_revisions WHERE entity_id=? AND revision=?",
                         (one["id"], revision)).fetchone()
    assert json.loads(old[0])["display_name"] == "Марина"


@pytest.mark.parametrize("aliases", [None, True, "Маруся", [None], [3], [""], ["a"] * 6,
    ["@name"], ["a,b"], ["a:b"], ["Модель"], ["Coordinator"], ["a\u200bb"], ["a\nb"], ["a\tb"], ["x" * 81]])
def test_bad_aliases_rejected_without_activating_a_persona(env, aliases):
    with pytest.raises(ContractError, match="persona_alias"):
        create(env, payload={"name": "Test", "aliases": aliases})
    assert env.service.list(context=env.ctx, admit=env.admit, domain="personas")["items"] == []


@pytest.mark.parametrize("aliases", [["équipe", "e\u0301quipe"], ["MAIN", "main"], ["ＡＢ", "ab"]])
def test_unicode_alias_ambiguity_rejected(env, aliases):
    with pytest.raises(ContractError, match="persona_aliases_ambiguous"):
        create(env, payload={"name": "Test", "aliases": aliases})


@pytest.mark.parametrize("value", [None, 0, 1, "true", "false", [], {}])
def test_main_is_strict_boolean_not_truthy(env, value):
    with pytest.raises(ContractError, match="persona_main_invalid"):
        create(env, payload={"name": "Test", "main_assistant": value})


def test_alias_and_name_conflicts_are_private_and_checked_at_activation(env):
    one = active(env, "Марина", aliases=["Лидер"])
    for name, aliases in (("Лидер", []), ("Другой", ["марина"]), ("Другой", ["лидер"])):
        draft = create(env, payload={"name": name, "aliases": aliases}, key="draft-" + uuid4().hex)["item"]
        with pytest.raises(ContractError, match="persona_alias_already_assigned"):
            act(env, draft)
        assert get(env, "personas", draft["id"])["status"] == "draft"
    for ctx in (context(user=2), context(workspace="ws_other_persona")):
        item = create(env, payload={"name": "Other", "aliases": ["Лидер"], "main_assistant": True},
                      key="other-scope-identity", ctx=ctx)["item"]
        assert act(env, item, ctx=ctx)["item"]["status"] == "active"
    assert get(env, "personas", one["id"])["aliases"] == ["Лидер"]


def test_main_swap_requires_explicit_clear_and_keeps_suspended_slot(env):
    one = active(env, main_assistant=True)
    two = active(env, "Другая", key="identity-two")
    suspended = act(env, one, action="suspend")["item"]
    with pytest.raises(ContractError, match="persona_main_already_assigned"):
        act(env, two, action="update", payload={"name": two["title"], "main_assistant": True})
    with pytest.raises(ContractError, match="persona_selection_inactive"):
        resolve(env, "Сделай снимок рабочего стола MNQ 09-26, 5m")
    cleared = act(env, suspended, action="update", payload={"name": one["title"], "main_assistant": False})["item"]
    assert cleared["main_assistant"] is False
    chosen = act(env, two, action="update", payload={"name": two["title"], "main_assistant": True})["item"]
    assert resolve(env, "Рабочее поручение").persona_id == chosen["id"]
    assert get(env, "personas", one["id"])["status"] == "suspended"


@pytest.mark.parametrize("fields,error", [({"main_assistant": True}, "persona_main_already_assigned"),
                                         ({"aliases": ["Общий"]}, "persona_alias_already_assigned")])
def test_concurrent_identity_assignment_has_one_winner_in_real_sqlite(env, fields, error):
    drafts = [create(env, payload={"name": f"Person {index}", **fields}, key=f"concurrent-persona-{index}")["item"]
              for index in range(2)]
    def activate(item):
        try:
            return act(env, item)["item"]["status"]
        except ContractError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(activate, drafts))
    assert sorted(results) == sorted(["active", error])


def test_same_display_names_are_not_rewritten_and_uuid_choice_is_unambiguous(env):
    one = active(env)
    two = active(env, key="identity-same-name")
    with pytest.raises(ContractError, match="persona_address_ambiguous"):
        resolve(env, "Марина: задание")
    assert resolve(env, "задание", one["id"]).persona_id == one["id"]
    assert resolve(env, "задание", two["id"]).persona_id == two["id"]
    assert get(env, "personas", one["id"])["title"] == get(env, "personas", two["id"])["title"] == "Марина"


def test_address_selector_conflict_and_unknown_explicit_alias_do_not_fallback(env):
    one = active(env, aliases=["Маруся"], main_assistant=True)
    two = active(env, "Иван", key="identity-ivan")
    with pytest.raises(ContractError, match="persona_address_mismatch"):
        resolve(env, "Маруся, задание", two["id"])
    with pytest.raises(ContractError, match="persona_selection_unavailable"):
        resolve(env, "@чужой, задание")
    assert resolve(env, "Модель 00000000-0000-0000-0000-000000000001: json_arithmetic") is None
    assert resolve(env, "КОМАНДА: без известного адресата").message == "КОМАНДА: без известного адресата"
    assert resolve(env, "Задание без адресата").persona_id == one["id"]


@pytest.mark.parametrize("persona_id", ["", 1, [], "not-a-uuid", "../private", " " + str(uuid4())])
def test_invalid_selection_is_never_an_auto_selection(env, persona_id):
    active(env, main_assistant=True)
    with pytest.raises(ContractError, match="persona_selection_invalid"):
        resolve(env, "Задание", persona_id)


def test_foreign_draft_retired_and_nonhuman_selections_fail_closed(env):
    one = active(env, main_assistant=True)
    for ctx in (context(user=2), context(workspace="ws_other_persona")):
        with pytest.raises(ContractError, match="persona_selection_unavailable"):
            resolve(env, "Задание", one["id"], ctx=ctx)
        assert resolve(env, "Задание", ctx=ctx) is None
    for status in ("suspend", "archive"):
        one = act(env, one, action=status)["item"]
        with pytest.raises(ContractError, match="persona_selection_inactive"):
            resolve(env, "Задание", one["id"])
    actor = c.ActorRef(kind=c.ActorKind.SERVICE, actor_id=uuid4(), on_behalf_of=env.ctx.user_uuid)
    with pytest.raises(ContractError, match="persona_selection_invalid"):
        resolve(env, "Задание", ctx=replace(env.ctx, actor=actor))


def test_selected_binding_never_uses_another_persona_or_infers_role_by_name(model_setup):
    service, ctx, payload, *_ = model_setup
    model = connected(model_setup)
    assert identity.select_model(service, context=ctx, persona_id=payload["persona_id"]) == model["id"]
    with pytest.raises(ContractError, match="persona_application_role_mismatch"):
        identity.select_model(service, context=ctx, persona_id=payload["persona_id"], kind="backtest")
    other = service.connect(context=ctx, payload={**payload, "label": "Second connection"}, idempotency_key="second-identity-model")
    assert other["id"] != model["id"]
    with pytest.raises(ContractError, match="persona_model_ambiguous"):
        identity.select_model(service, context=ctx, persona_id=payload["persona_id"])


@pytest.mark.parametrize("source,enabled", [("telegram", True), ("app", False)])
def test_explicit_selection_cannot_escape_channel_or_flags(monkeypatch, source, enabled):
    monkeypatch.setattr(live_gateway, "configured", lambda *_: enabled)
    monkeypatch.setattr(domain_gateway, "access", lambda *_: pytest.fail("disabled selection read live domain"))
    kwargs = {"scope": {"workspace_id": "ws_test"}, "conversation_id": "chat-one", "request_id": "req-one", "source": source}
    assert identity.try_chat("Hello", **kwargs) is None
    with pytest.raises(ContractError, match="persona_chat_unavailable"):
        identity.try_chat("Hello", persona_id=str(uuid4()), **kwargs)


def test_existing_adapter_receives_exact_persona_and_original_text(model_setup, monkeypatch):
    service, ctx, payload, *_ = model_setup
    persona = service._get(ctx, EntityKind.PERSONA, payload["persona_id"])
    service._change(ctx, persona, display_name="Марина", profile=service._put(ctx, {"aliases": ["Маруся"]}))
    calls = []
    scope = {"workspace_id": ctx.scope.workspace_id}
    authorized = {"context": ctx, "chat_scope": scope, "admit": lambda: None}
    monkeypatch.setattr(live_gateway, "configured", lambda *_: True)
    monkeypatch.setattr(domain_gateway, "access", lambda _: authorized)
    monkeypatch.setattr(domain_gateway, "models", lambda _: service)
    monkeypatch.setattr(application_chat, "try_chat", lambda text, **kw: calls.append((text, kw)) or {"ok": True})
    monkeypatch.setattr(model_chat, "try_persona", lambda **_: pytest.fail("application route must not invoke model route"), raising=False)
    message = "@Маруся, сделай снимок рабочего стола MNQ 09-26, 5m"
    assert identity.try_chat(message, scope=scope, conversation_id="chat-id", request_id="request-1", source="app") == {"ok": True}
    assert calls[0][0] == "сделай снимок рабочего стола MNQ 09-26, 5m"
    assert calls[0][1]["user_message"] == message and calls[0][1]["persona_id"] == payload["persona_id"]
    assert calls[0][1]["persona_revision"] == service._get(ctx, EntityKind.PERSONA, payload["persona_id"]).header.revision


def test_unknown_selected_task_is_not_a_legacy_fallback(model_setup, monkeypatch):
    service, ctx, payload, *_ = model_setup
    scope = {"workspace_id": ctx.scope.workspace_id}
    authorized = {"context": ctx, "chat_scope": scope, "admit": lambda: None}
    monkeypatch.setattr(live_gateway, "configured", lambda *_: True)
    monkeypatch.setattr(domain_gateway, "access", lambda _: authorized)
    monkeypatch.setattr(domain_gateway, "models", lambda _: service)
    monkeypatch.setattr(application_chat, "try_chat", lambda *_a, **_kw: None)
    monkeypatch.setattr(model_chat, "try_persona", lambda **_: None, raising=False)
    with pytest.raises(ContractError, match="persona_task_not_supported"):
        identity.try_chat("Unknown task", scope=scope, conversation_id="chat-id", request_id="request-1",
                          source="app", persona_id=payload["persona_id"])
