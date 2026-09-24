"""Live public Community projection across one disposable Local Preview.

Only already-public publications cross this boundary. Imported rows are never
written back to either store. There is no identity, private-feed or chat proxy.
"""
from __future__ import annotations

import json
import base64

MARKER = "_preview_public_projection"


def _avatar_projection(path):
    if path is None or not path.is_file() or path.stat().st_size > 1024 * 1024:
        return None
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(path.suffix.lower())
    if not mime:
        return None
    return {"mime": mime, "data": base64.b64encode(path.read_bytes()).decode("ascii")}


def snapshot(doc, *, test=False, avatar_loader=None):
    from . import community, account_auth
    avatar_loader = avatar_loader or (lambda row: account_auth.avatar_file(row.get("user_id")))
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
        avatar = _avatar_projection(avatar_loader(row))
        profiles[-1].update(user_id=0, profile_visibility="network", allow_messages="nobody",
                            has_avatar=bool(avatar), **{MARKER: True})
        if avatar:
            profiles[-1]["_preview_avatar"] = avatar
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
    if preview_shared_models.transport_enabled():
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
            avatar_root = (container / "data" / "integrations" / "avatars").resolve()
            def child_avatar(row):
                uid = str(row.get("user_id") or "")
                if not uid.isdigit():
                    return None
                for ext in ("png", "jpg", "jpeg", "webp"):
                    candidate = (avatar_root / (uid + "." + ext)).resolve()
                    if candidate.parent == avatar_root and candidate.is_file():
                        return candidate
                return None
            public = snapshot(json.loads(path.read_text(encoding="utf-8")), test=True, avatar_loader=child_avatar)
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


def avatar_payload(profile_id):
    """Serve only projected public profile bytes through the existing endpoint."""
    from . import community
    with community._LOCK:
        row = community._profile_row(community._load(), profile_id) or {}
    value = row.get("_preview_avatar") if row.get(MARKER) else None
    if not isinstance(value, dict) or value.get("mime") not in {"image/png", "image/jpeg", "image/webp"}:
        return None
    try:
        payload = base64.b64decode(value.get("data", ""), validate=True)
    except (ValueError, TypeError):
        return None
    return (payload, value["mime"]) if 0 < len(payload) <= 1024 * 1024 else None
