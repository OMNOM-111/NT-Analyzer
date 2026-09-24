"""Live public Community projection across one disposable Local Preview.

Only already-public publications cross this boundary. Imported rows are never
written back to either store. There is no identity, private-feed or chat proxy.
"""
from __future__ import annotations

import json
from pathlib import Path

MARKER = "_preview_public_projection"


def snapshot(doc, *, test=False):
    from . import community
    posts = [row for row in doc.get("posts", []) if not row.get(MARKER)
             and row.get("visibility", "network") == "network"
             and not row.get("removed_at_utc") and community._post_visible(doc, row, "preview-public-reader")]
    author_ids = {str(row.get("author_profile_id")) for row in posts}
    author_ids.update(str(row.get("published_by_profile_id")) for row in posts)
    profiles = []
    for row in doc.get("profiles", []):
        if row.get(MARKER) or (row.get("profile_visibility", "network") != "network"
                               and str(row.get("profile_id")) not in author_ids):
            continue
        public = community._public_profile(doc, row, "preview-public-reader")
        profiles.append({key: public[key] for key in
            ("profile_id", "display_name", "username", "role_label", "bio", "joined_at_utc")})
        profiles[-1].update(user_id=0, profile_visibility="network", allow_messages="nobody",
                            has_avatar=False, **{MARKER: True})
        if test:
            profiles[-1]["role_label"] = "TEST / PREVIEW"
    fields = ("post_id", "author_profile_id", "text", "kind", "visibility", "hashtags",
              "created_at_utc", "updated_at_utc", "publisher_org_id", "published_by_profile_id",
              "published_by_ai_agent", "corrects_post_id")
    projected = []
    for row in posts:
        public = community._public_social_post(doc, row, "preview-public-reader")
        projected.append({key: row[key] for key in fields if key in row})
        projected[-1].update(object_snapshot=public["object"], attachments=public["attachments"],
                             **{MARKER: True})
    organizations = []
    org_ids = {str(row.get("publisher_org_id")) for row in posts}
    for row in doc.get("organizations", []):
        if str(row.get("org_id")) not in org_ids:
            continue
        public = community._public_organization(doc, row, "preview-public-reader")
        organizations.append({"org_id": public["org_id"], "name": public["display_name"],
            "handle": public["username"], "description": public["description"],
            "created_at_utc": public["created_at_utc"], "owner_profile_id": "",
            "editor_profile_ids": [], MARKER: True})
    return {"profiles": profiles, "posts": projected, "organizations": organizations}


def overlay(doc):
    from . import runtime_env, preview_shared_models, dev_preview, community
    if not runtime_env.is_development():
        return doc
    if preview_shared_models.enabled():
        try:
            public = preview_shared_models.request("/social", {})
        except Exception as exc:
            raise community.CommunityError("Публичная лента временно недоступна. Повторите загрузку.", 503) from exc
    else:
        active = dev_preview._ACTIVE_SANDBOX
        if not active or not dev_preview._process_alive(active):
            return doc
        container = dev_preview._validated_preview_container(active)
        if not container:
            return doc
        path = container / "data" / "runtime" / "community.json"
        try:
            public = snapshot(json.loads(path.read_text(encoding="utf-8")), test=True)
        except FileNotFoundError:
            return doc
    for key in ("profiles", "posts", "organizations"):
        identity = {"profiles": "profile_id", "posts": "post_id", "organizations": "org_id"}[key]
        known = {row.get(identity) for row in doc.get(key, [])}
        doc.setdefault(key, []).extend(row for row in public.get(key, []) if row.get(identity) not in known)
    doc["posts"].sort(key=lambda row: (str(row.get("created_at_utc", "")), str(row.get("post_id", ""))))
    return doc


def local_only(doc):
    return {key: [row for row in value if not isinstance(row, dict) or not row.get(MARKER)]
            if isinstance(value, list) else value for key, value in doc.items()}
