"""Permanent record — Original ideas. Permanent history. Transparent corrections.

SF Social's founding rule, tested where it is enforced rather than where it is
displayed. A timeline you can prune after the fact says nothing about a person;
it says what they chose to leave standing. So a member cannot delete an
original, rewrite its content, or change its date or authorship, and the rule
binds the owner as an author exactly as it binds everyone else.

The one exception is administrative removal. It is disclosed rather than
hidden — a hidden backdoor would make the public promise a lie — it requires
owner authority, a reason code and a written reason, and it writes an
append-only audit record before it touches anything.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app import community

ROOT = Path(__file__).resolve().parents[1]
AURORA = ROOT / "app" / "static" / "aurora"
DOCS = ROOT / "docs"
COMMUNITY_JS = (AURORA / "assets" / "pages" / "community.js").read_text(encoding="utf-8")
COMMUNITY_HTML = (AURORA / "community.html").read_text(encoding="utf-8")
DOCUMENTS_JS = (AURORA / "assets" / "pages" / "documents.js").read_text(encoding="utf-8")
COMMUNITY_PY = (ROOT / "app" / "community.py").read_text(encoding="utf-8")
SERVER_PY = (ROOT / "app" / "server.py").read_text(encoding="utf-8")


@pytest.fixture()
def community_store(tmp_path, monkeypatch):
    monkeypatch.setattr(community, "_root", lambda: tmp_path)
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def as_owner(monkeypatch):
    """Owner authority read from the account store, as the module reads it."""
    from app import account_auth
    monkeypatch.setattr(
        account_auth, "find_active_user",
        lambda uid: {"user_id": uid, "is_owner": uid == 1, "user_uuid": f"uuid-{uid}"},
    )
    return 1


def _author(user_id: int = 42) -> str:
    return community.ensure_social_profile(
        user_id, display_name="Author", username=f"author_{user_id}",
    )["profile"]["profile_id"]


def _removal(owner_id=1, **kwargs):
    payload = {
        "reason_code": "moderation_policy",
        "reason": "нарушение правил сообщества",
    }
    payload.update(kwargs)
    target_type = payload.pop("target_type")
    target_id = payload.pop("target_id")
    return community.owner_remove_content(owner_id, target_type, target_id, **payload)


# =========================================================================== #
# The member
# =========================================================================== #
def test_a_member_cannot_delete_their_own_post(community_store):
    _author()
    post = community.create_social_post(42, text="Первая мысль")["post"]

    with pytest.raises(community.CommunityError) as refused:
        community.delete_social_post(42, post["post_id"])

    assert refused.value.status == 403
    stored = next(row for row in community._load()["posts"]
                  if row["post_id"] == post["post_id"])
    assert not stored.get("deleted_at_utc")
    assert [row["post_id"] for row in community.social_feed(42)["posts"]] == [post["post_id"]]


def test_a_member_cannot_delete_their_own_comment(community_store):
    _author()
    community.ensure_social_profile(99, display_name="Reader", username="reader_99")
    post = community.create_social_post(42, text="Пост")["post"]
    commented = community.comment_on_post(99, post["post_id"], text="Комментарий")
    comment_id = commented["post"]["recent_comments"][-1]["comment_id"]

    with pytest.raises(community.CommunityError) as refused:
        community.delete_social_comment(99, comment_id)

    assert refused.value.status == 403
    stored = next(row for row in community._load()["comments"]
                  if row["comment_id"] == comment_id)
    assert not stored.get("deleted_at_utc")


def test_a_member_cannot_rewrite_content_date_or_authorship(community_store):
    """Editing is absent by construction: no function, no route, no field."""
    editors = [name for name in dir(community)
               if name.startswith(("edit_social", "update_social_post", "rewrite_"))]
    assert editors == []
    for forbidden in ("def edit_social_post", "def update_social_post"):
        assert forbidden not in COMMUNITY_PY


def test_the_rule_binds_the_owner_as_an_author(community_store, as_owner):
    _author(1)
    post = community.create_social_post(1, text="Слово владельца")["post"]

    with pytest.raises(community.CommunityError) as refused:
        community.delete_social_post(1, post["post_id"], moderator=True)

    assert refused.value.status == 403
    stored = next(row for row in community._load()["posts"]
                  if row["post_id"] == post["post_id"])
    assert not stored.get("deleted_at_utc")


def test_a_member_still_cannot_touch_someone_elses_post(community_store):
    _author()
    community.ensure_social_profile(99, display_name="Reader", username="reader_99")
    post = community.create_social_post(99, text="Чужая публикация")["post"]

    with pytest.raises(community.CommunityError) as refused:
        community.delete_social_post(42, post["post_id"])

    assert refused.value.status == 403


# =========================================================================== #
# Transparent corrections
# =========================================================================== #
def test_a_correction_is_a_new_object_beside_the_original(community_store):
    _author()
    original = community.create_social_post(42, text="Скажу с ошибкой")["post"]

    correction = community.create_social_post(
        42, text="Уточняю: вот как правильно", corrects_post_id=original["post_id"],
    )["post"]

    assert correction["post_id"] != original["post_id"]
    assert correction["corrects_post_id"] == original["post_id"]
    ids = {row["post_id"] for row in community.social_feed(42)["posts"]}
    assert ids == {original["post_id"], correction["post_id"]}


def test_the_original_names_its_corrections_too(community_store):
    _author()
    original = community.create_social_post(42, text="Первая версия")["post"]
    correction = community.create_social_post(
        42, text="Исправление", corrects_post_id=original["post_id"],
    )["post"]

    refreshed = next(row for row in community.social_feed(42)["posts"]
                     if row["post_id"] == original["post_id"])
    assert refreshed["corrected_by_post_ids"] == [correction["post_id"]]
    assert refreshed["text"] == "Первая версия"       # untouched
    assert refreshed["created_at_utc"] == original["created_at_utc"]


def test_a_correction_can_only_point_at_your_own_standing_post(community_store):
    _author()
    community.ensure_social_profile(99, display_name="Reader", username="reader_99")
    theirs = community.create_social_post(99, text="Чужое")["post"]

    with pytest.raises(community.CommunityError) as refused:
        community.create_social_post(42, text="Правлю чужое", corrects_post_id=theirs["post_id"])
    assert refused.value.status == 403

    with pytest.raises(community.CommunityError) as missing:
        community.create_social_post(42, text="Правлю ничто", corrects_post_id="cpost_nope")
    assert missing.value.status == 404


# =========================================================================== #
# The interface is told the truth
# =========================================================================== #
def test_a_post_never_advertises_a_delete_control(community_store):
    _author()
    community.create_social_post(42, text="Пост")

    post = community.social_feed(42)["posts"][0]
    assert post["can_delete"] is False
    assert post["is_author"] is True
    assert post["permanent"] is True


def test_a_comment_never_advertises_a_delete_control(community_store):
    _author()
    post = community.create_social_post(42, text="Пост")["post"]
    community.comment_on_post(42, post["post_id"], text="Свой комментарий")

    comment = community.social_feed(42)["posts"][0]["recent_comments"][-1]
    assert comment["can_delete"] is False
    assert comment["is_author"] is True


def test_the_feed_carries_the_one_wording_of_the_rule(community_store):
    _author()
    feed = community.social_feed(42)

    assert feed["permanent_record"] is True
    assert feed["permanence_notice"] == community.PERMANENT_RECORD_NOTICE
    assert "постоянной истории" in feed["permanence_notice"]


# =========================================================================== #
# Administrative removal — authority
# =========================================================================== #
def test_a_member_cannot_reach_the_administrative_procedure(community_store, as_owner):
    _author()
    post = community.create_social_post(42, text="Пост")["post"]

    with pytest.raises(community.CommunityError) as refused:
        _removal(42, target_type="post", target_id=post["post_id"])
    assert refused.value.status == 403


def test_an_ai_without_owner_authority_is_refused(community_store, as_owner):
    """An agent has no standing of its own. Asking as one is a 403, not a
    different code path."""
    _author()
    post = community.create_social_post(42, text="Пост")["post"]

    with pytest.raises(community.CommunityError) as refused:
        _removal(
            42, target_type="post", target_id=post["post_id"],
            actor="ai", ai_agent_id="claude-opus-5", source="ai_assisted",
        )
    assert refused.value.status == 403
    assert community._load()["posts"][0]["text"] == "Пост"


def test_an_ai_acting_for_the_owner_uses_the_same_audited_flow(community_store, as_owner):
    _author()
    post = community.create_social_post(42, text="Пост")["post"]

    out = _removal(
        1, target_type="post", target_id=post["post_id"],
        reason_code="legal_request", reason="удаление по решению суда",
        actor="ai", ai_agent_id="claude-opus-5", source="ai_assisted",
    )

    entry = out["audit"]
    assert entry["actor"] == "ai"
    assert entry["ai_agent_id"] == "claude-opus-5"
    assert entry["source"] == "ai_assisted"
    # The chain shows the owner as the authority and the agent as the hand.
    assert entry["actor_chain"] == ["owner:1", "ai:claude-opus-5"]
    assert entry["authority_user_id"] == 1


def test_an_ai_is_never_recorded_as_the_owner(community_store, as_owner):
    _author()
    post = community.create_social_post(42, text="Пост")["post"]

    entry = _removal(
        1, target_type="post", target_id=post["post_id"],
        reason_code="legal_request", reason="удаление по решению суда",
        actor="ai", ai_agent_id="claude-opus-5", source="ai_assisted",
    )["audit"]

    assert entry["actor_chain"][0] == "owner:1"
    assert not entry["actor_chain"][0].startswith("ai:")
    assert entry["authority_user_id"] == 1


def test_an_ai_actor_must_name_itself(community_store, as_owner):
    _author()
    post = community.create_social_post(42, text="Пост")["post"]

    with pytest.raises(community.CommunityError) as unnamed:
        _removal(1, target_type="post", target_id=post["post_id"], actor="ai")
    assert unnamed.value.status == 400


def test_the_removal_is_shown_before_it_happens(community_store, as_owner):
    """The step an agent must take first: name the object, change nothing."""
    profile_id = _author()
    post = community.create_social_post(42, text="Пост")["post"]

    preview = community.preview_owner_removal(1, "post", post["post_id"])["preview"]

    assert preview["target_id"] == post["post_id"]
    assert preview["author_profile_id"] == profile_id
    assert preview["author_username"] == "author_42"
    assert preview["created_at_utc"]
    assert preview["content_hash"].startswith("sha256:")
    assert preview["default_operation"] == "moderation_removal"
    assert "legal_request" in preview["reason_codes"]
    # Nothing moved.
    assert community.social_feed(42)["posts"][0]["post_id"] == post["post_id"]


def test_the_preview_is_owner_only(community_store, as_owner):
    _author()
    post = community.create_social_post(42, text="Пост")["post"]
    with pytest.raises(community.CommunityError) as refused:
        community.preview_owner_removal(42, "post", post["post_id"])
    assert refused.value.status == 403


# =========================================================================== #
# Administrative removal — grounds
# =========================================================================== #
def test_a_reason_code_and_a_written_reason_are_both_required(community_store, as_owner):
    _author()
    post = community.create_social_post(42, text="Пост")["post"]

    with pytest.raises(community.CommunityError) as no_code:
        _removal(1, target_type="post", target_id=post["post_id"], reason_code="")
    assert no_code.value.status == 400

    with pytest.raises(community.CommunityError) as bad_code:
        _removal(1, target_type="post", target_id=post["post_id"], reason_code="потому что")
    assert bad_code.value.status == 400

    for blank in ("", "   ", "суд"):
        with pytest.raises(community.CommunityError) as no_reason:
            _removal(1, target_type="post", target_id=post["post_id"], reason=blank)
        assert no_reason.value.status == 400

    assert community._load()["posts"][0]["text"] == "Пост"
    assert community._load().get("audit_log", []) == []


def test_hard_erasure_needs_grounds_that_demand_it(community_store, as_owner):
    """A rules violation is answered by a tombstone, not by clearing content."""
    _author()
    post = community.create_social_post(42, text="Пост")["post"]

    with pytest.raises(community.CommunityError) as refused:
        _removal(
            1, target_type="post", target_id=post["post_id"],
            operation="hard_erasure", reason_code="moderation_policy",
            reason="нарушение правил сообщества",
        )
    assert refused.value.status == 400
    assert community._load()["posts"][0]["text"] == "Пост"


# =========================================================================== #
# Administrative removal — the two operations
# =========================================================================== #
def test_moderation_removal_is_the_default_and_keeps_the_content(community_store, as_owner):
    _author()
    post = community.create_social_post(42, text="Исходный текст")["post"]

    out = _removal(1, target_type="post", target_id=post["post_id"])

    assert out["operation"] == "moderation_removal"
    stored = community._load()["posts"][0]
    assert stored["text"] == "Исходный текст"        # retained for the record
    assert stored["removed_at_utc"]
    assert stored["removal_operation"] == "moderation_removal"
    assert stored.get("content_erased") is not True


def test_hard_erasure_actually_clears_the_content(community_store, as_owner):
    _author()
    post = community.create_social_post(42, text="Персональные данные")["post"]

    _removal(
        1, target_type="post", target_id=post["post_id"],
        operation="hard_erasure", reason_code="privacy_request",
        reason="требование об удалении персональных данных",
    )

    doc = community._load()
    stored = doc["posts"][0]
    assert stored["text"] == ""
    assert stored["attachments"] == []
    assert stored["content_erased"] is True
    # And the content is not hiding in the audit trail either.
    assert "Персональные данные" not in str(doc["audit_log"])


def test_even_a_hard_erasure_keeps_a_non_content_audit_record(community_store, as_owner):
    _author()
    post = community.create_social_post(42, text="Персональные данные")["post"]
    expected = community.preview_owner_removal(1, "post", post["post_id"])["preview"]

    _removal(
        1, target_type="post", target_id=post["post_id"],
        operation="hard_erasure", reason_code="privacy_request",
        reason="требование об удалении персональных данных",
    )

    entry = community.owner_audit_log(1)["entries"][0]
    assert entry["operation"] == "hard_erasure"
    assert entry["content_hash"] == expected["content_hash"]
    assert entry["content_length"] == len("Персональные данные")
    assert entry["author_profile_id"]
    assert entry["created_at_utc"] and entry["occurred_at_utc"]


# =========================================================================== #
# Administrative removal — the audit trail
# =========================================================================== #
def test_the_audit_record_carries_every_required_field(community_store, as_owner):
    profile_id = _author()
    post = community.create_social_post(42, text="Пост")["post"]

    out = _removal(
        1, target_type="post", target_id=post["post_id"],
        reason_code="illegal_content", reason="незаконное содержимое, обращение №14",
        correlation_id="case-14",
    )

    entry = out["audit"]
    for field in (
        "target_id", "target_type", "author_profile_id", "actor", "actor_chain",
        "authority_user_id", "occurred_at_utc", "reason_code", "reason_label",
        "reason", "source", "content_hash", "object_version", "operation",
        "audit_id", "correlation_id",
    ):
        assert entry.get(field) not in (None, ""), field
    assert entry["target_id"] == post["post_id"]
    assert entry["author_profile_id"] == profile_id
    assert entry["reason_code"] == "illegal_content"
    assert entry["correlation_id"] == "case-14"


def test_the_audit_entry_is_written_before_the_object_is_touched(community_store):
    """A removal interrupted halfway must still leave its trace."""
    body = COMMUNITY_PY[COMMUNITY_PY.index("def _apply_removal("):]
    body = body[:body.index("\ndef ")]
    assert body.index('doc.setdefault("audit_log", []).append(entry)') \
        < body.index('row["removed_at_utc"]')


def test_the_audit_log_only_grows(community_store, as_owner):
    _author()
    first = community.create_social_post(42, text="Первый")["post"]
    second = community.create_social_post(42, text="Второй")["post"]

    _removal(1, target_type="post", target_id=first["post_id"], reason="первое основание")
    _removal(1, target_type="post", target_id=second["post_id"], reason="второе основание")

    log = community.owner_audit_log(1)
    assert log["total"] == 2
    assert {row["target_id"] for row in log["entries"]} == {first["post_id"], second["post_id"]}


def test_nothing_in_the_module_removes_an_audit_entry():
    """An audit trail a user can edit is not an audit trail."""
    uses = [line.strip() for line in COMMUNITY_PY.splitlines() if "audit_log" in line]
    for line in uses:
        assert not any(bad in line for bad in ("pop(", "del ", "remove(", "[:] =", "clear()")), line
    assert "def owner_audit_log" in COMMUNITY_PY
    # And no route offers one either.
    assert "/api/community/v2/owner/audit" in SERVER_PY
    audit_routes = [line for line in SERVER_PY.splitlines() if "owner/audit" in line]
    assert all("delete" not in line.lower() for line in audit_routes)


def test_a_member_cannot_read_the_audit_log(community_store, as_owner):
    with pytest.raises(community.CommunityError) as refused:
        community.owner_audit_log(42)
    assert refused.value.status == 403


def test_the_audit_survives_a_restart(community_store, as_owner):
    _author()
    post = community.create_social_post(42, text="Пост")["post"]
    _removal(1, target_type="post", target_id=post["post_id"], reason="основание для удаления")

    # Read the store back the way a freshly started process would.
    raw = community._load()
    assert raw["audit_log"][0]["target_id"] == post["post_id"]
    reloaded = community.owner_audit_log(1)
    assert reloaded["total"] == 1
    assert reloaded["entries"][0]["target_id"] == post["post_id"]


def test_report_moderation_writes_the_same_audit_record(community_store, as_owner):
    """One removal path, one trail: a takedown from the report queue is
    recorded exactly like any other."""
    _author()
    community.ensure_social_profile(99, display_name="Reader", username="reader_99")
    post = community.create_social_post(42, text="На рассмотрении")["post"]
    report = community.report_social_target(
        99, post["post_id"], target_type="post", reason="policy review",
    )

    resolved = community.moderate_social_report(
        1, report["report_id"], action="remove", note="подтверждённое нарушение правил",
    )

    assert resolved["content_removed"] is True
    entry = community.owner_audit_log(1)["entries"][0]
    assert entry["source"] == "moderation_queue"
    assert entry["reason_code"] == "moderation_policy"
    assert entry["correlation_id"] == report["report_id"]
    assert entry["operation"] == "moderation_removal"
    assert community._load()["posts"][0]["text"] == "На рассмотрении"


def test_report_moderation_also_demands_a_written_reason(community_store, as_owner):
    _author()
    community.ensure_social_profile(99, display_name="Reader", username="reader_99")
    post = community.create_social_post(42, text="На рассмотрении")["post"]
    report = community.report_social_target(
        99, post["post_id"], target_type="post", reason="policy review",
    )

    with pytest.raises(community.CommunityError) as refused:
        community.moderate_social_report(1, report["report_id"], action="remove", note="")
    assert refused.value.status == 400


# =========================================================================== #
# What readers see afterwards
# =========================================================================== #
def test_removed_content_leaves_recommendation_and_other_walls(community_store, as_owner):
    profile_id = _author()
    community.ensure_social_profile(99, display_name="Reader", username="reader_99")
    post = community.create_social_post(42, text="Исходный текст")["post"]

    _removal(1, target_type="post", target_id=post["post_id"], reason="основание для удаления")

    assert community.social_feed(99)["posts"] == []
    assert community.social_feed(42)["posts"] == []
    assert community.social_profile(99, profile_id)["posts"] == []
    assert "Исходный текст" not in str(community.social_feed(99))


def test_the_author_sees_a_tombstone_rather_than_a_silent_gap(community_store, as_owner):
    profile_id = _author()
    post = community.create_social_post(42, text="Исходный текст")["post"]

    _removal(1, target_type="post", target_id=post["post_id"], reason="основание для удаления")

    wall = community.social_profile(42, profile_id)["posts"]
    assert len(wall) == 1
    marker = wall[0]
    assert marker["removed"] is True
    assert marker["text"] == community.TOMBSTONE_POST_TEXT
    assert "Исходный текст" not in str(marker)
    assert marker["author"] is None
    assert marker["can_delete"] is False


def test_a_removed_comment_becomes_a_tombstone_in_the_thread(community_store, as_owner):
    _author()
    community.ensure_social_profile(99, display_name="Reader", username="reader_99")
    post = community.create_social_post(42, text="Пост")["post"]
    commented = community.comment_on_post(99, post["post_id"], text="Грубый комментарий")
    comment_id = commented["post"]["recent_comments"][-1]["comment_id"]

    _removal(1, target_type="comment", target_id=comment_id, reason="нарушение правил сообщества")

    thread = community.social_feed(42)["posts"][0]
    marker = thread["recent_comments"][-1]
    assert marker["removed"] is True
    assert marker["text"] == community.TOMBSTONE_COMMENT_TEXT
    assert "Грубый" not in str(thread)
    assert thread["comment_count"] == 0


def test_a_removal_cannot_be_applied_twice(community_store, as_owner):
    _author()
    post = community.create_social_post(42, text="Пост")["post"]
    _removal(1, target_type="post", target_id=post["post_id"], reason="первое основание")

    with pytest.raises(community.CommunityError) as again:
        _removal(1, target_type="post", target_id=post["post_id"], reason="второе основание")
    assert again.value.status == 409


# =========================================================================== #
# Nothing hidden
# =========================================================================== #
def test_the_interface_offers_no_delete_control():
    assert "data-delete-post" not in COMMUNITY_JS
    assert "data-delete-comment" not in COMMUNITY_JS
    assert "communityV2DeletePost" not in COMMUNITY_JS
    assert "communityV2DeleteComment" not in COMMUNITY_JS


def test_the_composer_warns_before_the_member_publishes():
    assert 'id="community-permanence-note"' in COMMUNITY_HTML
    assert "постоянной истории" in COMMUNITY_HTML
    assert "applyPermanenceNotice(doc)" in COMMUNITY_JS


def test_every_removal_route_is_named_in_the_documentation():
    """No hidden backdoor-delete: each route that removes content is disclosed."""
    doc = (DOCS / "product" / "PERMANENT_RECORD.md").read_text(encoding="utf-8")
    for route in ("/api/community/v2/owner/remove",
                  "/api/community/v2/owner/audit",
                  "/api/community/v2/owner/removal-preview"):
        assert route in SERVER_PY, route
        assert route in doc, route


def test_the_principle_is_stated_for_users_in_their_own_documents():
    assert "p-permanence" in DOCUMENTS_JS
    assert "Постоянная запись" in DOCUMENTS_JS
    assert community.PERMANENT_RECORD_PRINCIPLE in DOCUMENTS_JS
    doc = (DOCS / "product" / "PERMANENT_RECORD.md").read_text(encoding="utf-8")
    assert community.PERMANENT_RECORD_PRINCIPLE in doc
    assert "owner_remove_content" in doc
    for field in ("reason_code", "correlation_id", "actor_chain", "content_hash"):
        assert field in doc, field


def test_database_cleanup_is_documented_as_a_separate_operation():
    doc = (DOCS / "product" / "PERMANENT_RECORD.md").read_text(encoding="utf-8")
    assert "Development" in doc
    assert "Production" in doc
    assert "maintenance" in doc.lower()
