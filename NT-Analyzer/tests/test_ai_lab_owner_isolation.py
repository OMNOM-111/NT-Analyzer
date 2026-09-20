"""The Lab is one workspace's work: its content answers only to the owner.

The AI Center's own projections already refuse another workspace, but the Lab's
HTTP surface answered anyone signed in - the owner's knowledge base, their
research catalogue, their matrix and their statistics among it. The chat and
the local model bootstrap are per-user and stay open (owner, 20.09.2026).
"""
from __future__ import annotations

import pytest

from app import server

# Everything here is the owner's own work, whatever the method.
OWNER_ONLY = (
    "/api/ai-lab/knowledge-base",
    "/api/ai-lab/researches",
    "/api/ai-lab/researches/RES-1",
    "/api/ai-lab/experiments",
    "/api/ai-lab/experiments/EXP-1/activity",
    "/api/ai-lab/summary",
    "/api/ai-lab/performance",
    "/api/ai-lab/model-performance",
    "/api/ai-lab/matrix",
    "/api/ai-lab/portfolio",
    "/api/ai-lab/calendar",
    "/api/ai-lab/lifecycle",
    "/api/ai-lab/cell-history",
    "/api/ai-lab/errors/summary",
    "/api/ai-lab/current",
    "/api/ai-lab/run/status",
    "/api/ai-lab/chief-agent",
    "/api/ai-lab/cloud-agents/status",
    "/api/ai-agents",
    "/api/ai-agents/usage",
)

# The chat a person has with their own agents, and what that chat needs.
SHARED = (
    "/api/ai-lab/orchestrator/conversations",
    "/api/ai-lab/orchestrator/conversations/default",
    "/api/ai-lab/orchestrator/message",
    "/api/ai-lab/orchestrator/speak",
    "/api/ai-lab/domain-agents",
    "/api/ai-lab/domain-agents/voices",
    "/api/ai-lab/domain-agents/message",
    "/api/ai-lab/bootstrap/status",
    "/api/ai-lab/bootstrap/start",
    "/api/ai-lab/lm-studio/health",
    "/api/ai-lab/ratings",
    "/api/ai-lab/tts/catalog",
)


@pytest.mark.parametrize("path", OWNER_ONLY)
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_the_labs_own_content_answers_only_the_owner(path, method):
    assert server._is_owner_only_api_path(path, method) is True


@pytest.mark.parametrize("path", SHARED)
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_a_persons_own_chat_and_its_plumbing_stay_open(path, method):
    assert server._is_owner_only_api_path(path, method) is False


def test_the_ai_center_keeps_answering_every_workspace():
    """Its own routes carry their own admission; this gate must not shadow them."""
    for path in ("/api/ai-control-center/overview", "/api/ai-control-center/tasks",
                 "/api/ai-control-center/domains/models", "/api/ai-control-center/domains/memory",
                 "/api/ai-control-center/goal"):
        assert server._is_owner_only_api_path(path, "GET") is False


def test_the_owners_archive_and_duty_answer_the_owner_alone():
    """Gated in the projection, where the workspace and runtime are known."""
    from app.ai_control_center import duty_bridge, legacy_view
    from app.ai_control_center.states import ContractError

    stranger = {"chat_scope": {"is_owner": False, "uses_owner_runtime": False, "membership_role": "member"}}
    for call in (lambda: legacy_view.overview(stranger), lambda: legacy_view.agents(stranger),
                 lambda: legacy_view.calls(stranger), lambda: legacy_view.report(stranger),
                 lambda: duty_bridge.state(stranger)):
        with pytest.raises(ContractError):
            call()
