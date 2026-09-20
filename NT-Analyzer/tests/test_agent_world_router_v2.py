"""Router contracts on disposable records; no network, keys or live authority."""
from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest

from app.ai_control_center import contracts as c, router_v2 as router
from app.ai_control_center.flags import Flag, FlagRule, FlagSnapshot
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_models import setup, connected, response


def authorization(context, *, active=True, shadow=True):
    names = {"AI_CONTROL_CENTER_READ_MODEL", "AI_TASK_GRAPH_V2"}
    if active: names.add("AI_ROUTER_V2")
    if shadow: names.add("AI_ROUTER_SHADOW_V2")
    flags = [flag for flag in Flag if flag.value in names]
    return {"context": context, "admit": lambda: None, "snapshot": FlagSnapshot(revision="routing-contract-test", audit_ref=uuid4(),
        rules=tuple(FlagRule(environment=context.scope.environment, flag=flag, enabled=True, workspace_id=workspace)
                    for flag in flags for workspace in (None, context.scope.workspace_id)))}


def observed(setup, key="router-model-one", *, samples=3):
    service, context, *_ = setup
    model = connected(setup, key)
    checked = service.test(context=context, model_id=model["id"], idempotency_key=key + "-connection")
    service.execute(context=context, task_id=checked["id"])
    def execute(**kwargs):
        values = json.loads(kwargs["prompt"].split("Array: ")[1])
        return response(json.dumps({"count": len(values), "sum": sum(values), "min": min(values), "max": max(values), "mean": sum(values)/len(values)}))
    service.executor = execute
    for index in range(samples):
        task = service.start_task(context=context, model_id=model["id"], payload={"rubric_key": "json_arithmetic", "input_text": json.dumps([index, 2, 3])},
                                  idempotency_key=key + "-sample-" + str(index))
        service.execute(context=context, task_id=task["id"])
    return model


def request(model, **changes):
    return {"mode": "shadow", "task_class": "json_arithmetic", "candidate_model_ids": [model["id"]],
            "current_model_id": model["id"], "max_cost_usd": .01, "max_latency_ms": 1000, **changes}


def quote(**kwargs):
    return {"allowed": True, "cost_usd": .001}


def test_shadow_same_class_evidence_never_dispatches_or_grants_quality(setup):
    service, ctx, *_ = setup
    model = observed(setup)
    result = router.select(authorization(ctx), service, request(model), quote=quote)
    assert result["status"] == "selected" and result["effective_model_id"] == model["id"]
    candidate = result["candidates"][0]
    assert candidate["sample_size"] == 3 and len(candidate["evidence"]) == 3
    assert candidate["quality_score"] is None and result["quality_ranking"] is False
    assert result["dispatch_performed"] is result["permission_granted"] is False
    assert len({candidate[key] for key in ("model_id", "persona_id", "role_id", "provider_account_id")}) == 4


def test_arithmetic_observations_cannot_qualify_professional_plan_class(setup):
    service, ctx, *_ = setup
    model = observed(setup)
    result = router.select(authorization(ctx), service, request(model, task_class="backtest_spec"), quote=quote)
    assert result["status"] == "blocked" and result["selected_model_id"] is None
    assert result["candidates"][0]["reason_codes"] == ["routing_same_class_insufficient_data"]


def test_default_off_and_shadow_cannot_enable_active_selection(setup):
    service, ctx, *_ = setup
    model = connected(setup)
    for auth, body in ((authorization(ctx, active=False, shadow=False), request(model)),
                       (authorization(ctx, active=False), request(model, mode="active"))):
        with pytest.raises(ContractError, match="routing_disabled"):
            router.select(auth, service, body, quote=quote)


def test_known_same_class_verification_failure_is_not_hidden_by_three_successes(setup):
    service, ctx, *_ = setup
    model = observed(setup)
    service.executor = lambda **kwargs: response('{"wrong":true}')
    task = service.start_task(context=ctx, model_id=model["id"], payload={"rubric_key": "json_arithmetic", "input_text": "[99,22,-1]"},
        idempotency_key="same-class-known-failure")
    service.execute(context=ctx, task_id=task["id"])
    result = router.select(authorization(ctx), service, request(model), quote=quote)
    assert result["candidates"][0]["sample_size"] == 4
    assert result["candidates"][0]["reason_codes"] == ["routing_same_class_verification_failed"]
    assert result["selected_model_id"] is None and result["quality_ranking"] is False


@pytest.mark.parametrize("change", [{"mode": []}, {"task_class": {}}, {"candidate_model_ids": [{}]}])
def test_malformed_request_is_contract_denial_not_unhandled_type_error(setup, change):
    service, ctx, *_ = setup
    model = connected(setup)
    with pytest.raises(ContractError): router.select(authorization(ctx), service, request(model, **change), quote=quote)


@pytest.mark.parametrize("bad", [None, {}, {"allowed": True}, {"allowed": True, "cost_usd": float("nan")}, {"allowed": False, "cost_usd": 0}])
def test_unknown_current_price_or_permissions_fail_closed(setup, bad):
    service, ctx, *_ = setup
    model = observed(setup, samples=1)
    result = router.select(authorization(ctx), service, request(model), quote=None if bad is None else lambda **kw: bad)
    assert result["status"] == "blocked" and result["selected_model_id"] is None


@pytest.mark.parametrize("mutation", ["persona", "account", "model", "role", "not_connected"])
def test_inactive_separate_identity_cannot_route(setup, mutation):
    from app.ai_control_center.model_service import _id
    service, ctx, *_ = setup
    model = observed(setup, samples=1)
    current = service._get(ctx, EntityKind.MODEL, model["id"])
    profile = service._json(ctx, current.profile)
    if mutation == "not_connected":
        service._change(ctx, current, profile=service._put(ctx, {**profile, "connected": False}))
    else:
        kind, identity = {"persona": (EntityKind.PERSONA, profile["persona_id"]),
            "account": (EntityKind.PROVIDER_ACCOUNT, profile["provider_account_id"]), "model": (EntityKind.MODEL, model["id"]),
            "role": (EntityKind.AGENT_ROLE, _id(ctx, "role:model-response"))}[mutation]
        service._change(ctx, service._get(ctx, kind, identity), "suspended")
    result = router.select(authorization(ctx), service, request(model), quote=quote)
    assert result["selected_model_id"] is None


def test_stale_statistics_and_constraints_block_selection(setup):
    service, ctx, *_ = setup
    model = observed(setup)
    auth = authorization(ctx)
    late = router.select(auth, service, request(model), quote=quote, now=datetime.now(timezone.utc) + timedelta(days=31))
    assert late["selected_model_id"] is None
    for body in (request(model, max_cost_usd=0), request(model, max_latency_ms=1)):
        assert router.select(auth, service, body, quote=quote)["selected_model_id"] is None


def test_active_requires_its_own_flag_and_current_budget(setup):
    service, ctx, *_ = setup
    model = observed(setup)
    auth = authorization(ctx)
    selected = router.select(auth, service, request(model, mode="active"), quote=quote)
    assert selected["status"] == "selected" and selected["effective_model_id"] == model["id"]
    service.admit = lambda *args: (_ for _ in ()).throw(ContractError("budget_revoked")) if args[1] == "task" else None
    denied = router.select(auth, service, request(model, mode="active"), quote=quote)
    assert denied["status"] == "blocked"


def test_foreign_model_discloses_no_related_identifiers(setup):
    service, ctx, *_ = setup
    model = connected(setup)
    fake = str(uuid4())
    result = router.select(authorization(ctx), service, request(model, candidate_model_ids=[model["id"], fake]), quote=quote)
    row = next(row for row in result["candidates"] if row["model_id"] == fake)
    assert row["eligible"] is False and "persona_id" not in row and "provider_account_id" not in row

def priced(cheap, expensive):
    """A trusted server quote: the cheaper candidate is not the current one."""
    def quote(*, context, model, account, profile):
        identity = str(model.header.entity_id)
        return {"allowed": True, "cost_usd": .0005 if identity == cheap["id"] else .004}
    return quote


def test_active_decision_is_actually_used_and_grants_nothing_by_itself(setup):
    """An advisory decision is only real once the work runs where it points.

    Shadow mode reports the same ranking but keeps the caller's model, so
    running both modes over identical evidence separates "the router had an
    opinion" from "the opinion changed which model answered".
    """
    service, ctx, *_ = setup
    # `observed` installs its own arithmetic executor and leaves it there, so a
    # second model's connection test would not return CONNECTION_OK and that
    # candidate would stay unverified. Restore the fixture's executor between
    # the two so both models are genuinely connected.
    connection_executor = service.executor
    current = observed(setup, "router-usage-current")
    service.executor = connection_executor
    cheaper = observed(setup, "router-usage-cheaper")
    quote = priced(cheaper, current)
    body = request(current, candidate_model_ids=[current["id"], cheaper["id"]], current_model_id=current["id"])
    auth = authorization(ctx)

    advice = router.select(auth, service, {**body, "mode": "shadow"}, quote=quote)
    assert advice["selected_model_id"] == cheaper["id"]
    # Shadow ranked the same way and still leaves the caller where it was.
    assert advice["effective_model_id"] == current["id"] and advice["matches_legacy"] is False

    decision = router.select(auth, service, {**body, "mode": "active"}, quote=quote)
    assert decision["status"] == "selected" and decision["effective_model_id"] == cheaper["id"]
    assert decision["legacy_model_id"] == current["id"]
    assert decision["dispatch_performed"] is decision["permission_granted"] is False
    assert decision["quality_ranking"] is False and decision["decision_sha256"]

    # The ranking rests on this workspace's own verified observations of that
    # exact class, not on a self-reported score or a global registry.
    chosen = next(row for row in decision["candidates"] if row["model_id"] == cheaper["id"])
    assert chosen["sample_size"] == 3 and len(chosen["evidence"]) == 3
    assert chosen["quality_score"] is None and chosen["quality_effect"] == "none"
    for reference in chosen["evidence"]:
        record = service._get(ctx, EntityKind.EVALUATION, reference["entity_id"])
        assert str(record.model.entity_id) == cheaper["id"] and record.rubric_key == "json_arithmetic"

    # Use it: normal task ingress with the model the decision points at.
    served = []
    def execute(**kwargs):
        served.append(str(kwargs["model"].header.entity_id))
        values = json.loads(kwargs["prompt"].split("Array: ")[1])
        return response(json.dumps({"count": len(values), "sum": sum(values),
                                    "min": min(values), "max": max(values), "mean": sum(values) / len(values)}))
    service.executor = execute
    task = service.start_task(context=ctx, model_id=decision["effective_model_id"],
        payload={"rubric_key": "json_arithmetic", "input_text": json.dumps([7, 2, 3])},
        idempotency_key="router-decision-actually-used", conversation_id=uuid4(), message_id=uuid4())
    result = service.execute(context=ctx, task_id=task["id"])

    assert result["status"] == "succeeded" and result["evaluation"]["passed"]
    # The provider call went to the routed model, not to the one the caller
    # arrived with: the decision changed the outcome rather than describing it.
    assert served == [cheaper["id"]] and cheaper["id"] != current["id"]
    # Routing produced no new authority: the run still went through the normal
    # admission, and the decision itself remains advisory.
    assert router.select(auth, service, {**body, "mode": "active"}, quote=quote)["decision_sha256"]
    assert decision["permission_granted"] is False


def test_active_decision_is_not_used_when_its_own_flag_is_absent(setup):
    """Without AI_ROUTER_V2 there is no decision to follow, only shadow advice."""
    service, ctx, *_ = setup
    connection_executor = service.executor
    current = observed(setup, "router-unrouted-current")
    service.executor = connection_executor
    cheaper = observed(setup, "router-unrouted-cheaper")
    quote = priced(cheaper, current)
    body = request(current, mode="active", candidate_model_ids=[current["id"], cheaper["id"]],
                   current_model_id=current["id"])
    with pytest.raises(ContractError) as denied:
        router.select(authorization(ctx, active=False), service, body, quote=quote)
    assert denied.value.code == "routing_disabled"
    shadow = router.select(authorization(ctx, active=False), service, {**body, "mode": "shadow"}, quote=quote)
    assert shadow["selected_model_id"] == cheaper["id"] and shadow["effective_model_id"] == current["id"]
