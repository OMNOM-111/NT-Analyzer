"""Clean migration from the frozen «AI агенты» archive into the new registry.

Only historical facts cross over: the models themselves, what they actually
did, what it cost, and the ratings whose origin can be confirmed. The old
positions, the automatic assignments, the routing order and the old
Model <-> Role bindings do **not** cross over as configuration; a model that
once answered under an old role is recorded as provenance - what happened -
and never as a current pinning. New Agent Roles are created by the owner under
the rules in force, not by this migration.

The new registry becomes the single working registry only after the
reconciliation passes; until then `state()` says so and the marker is absent.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .. import runtime_env
from ..ai_lab import legacy_archive

SCHEMA_VERSION = 1
MARKER = "legacy-migration.ok.json"

# Fields of an old agent record that are current configuration of the old
# system. They are archived and readable in the Legacy view, and deliberately
# never become configuration of the new one.
NOT_MIGRATED = {
    "role": "старая должность",
    "purpose": "старая должность",
    "priority": "старое правило маршрутизации",
    "rotation_group": "старое правило маршрутизации",
    "enabled": "старое автоматическое назначение",
    "disabled_reason": "старое автоматическое назначение",
    "cooldown_until_utc": "старое правило маршрутизации",
    "cooldown_reason": "старое правило маршрутизации",
    "daily_budget_usd": "лимит старой системы",
    "monthly_budget_usd": "лимит старой системы",
}

# Facts about the model itself: identity, where it runs, what a call costs.
MODEL_FACTS = ("name", "provider", "model", "endpoint_type", "billing_mode", "account_name",
               "input_price_usd_per_m", "cached_input_price_usd_per_m", "output_price_usd_per_m",
               "credit_total_usd", "credit_started_at_utc", "credit_expires_at_utc",
               "pricing_status", "pricing_basis", "pricing_source_url", "created_at_utc", "updated_at_utc")


def registry_dir(project_root=None):
    return runtime_env.data_path("ai_control_center", "registry", project_root=project_root)


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def model_key(agent):
    """One stable key per old model record, so history and facts line up."""
    return f"{str(agent.get('provider') or 'unknown')}/{str(agent.get('model') or 'unknown')}#{str(agent.get('id') or '')}"


def _models(agents, archive_id):
    rows = []
    for agent in agents:
        fact = {key: agent.get(key) for key in MODEL_FACTS if agent.get(key) not in (None, "")}
        rows.append({"model_key": model_key(agent), "legacy_agent_id": agent.get("id"),
                     "origin": {"archive_id": archive_id, "source": "registry"},
                     "role": None,  # A migrated model holds no position. The owner assigns places.
                     **fact})
    return sorted(rows, key=lambda row: str(row.get("name") or ""))


def _history(rows, keys_by_agent, archive_id):
    """Every logged call, as the history it is: what ran, how it ended, what it cost."""
    history, seen = [], set()
    for row in rows:
        request_id = str(row.get("request_id") or "")
        if request_id and request_id in seen:
            continue
        seen.add(request_id)
        agent_id = str(row.get("agent_id") or "")
        history.append({
            "request_id": request_id or None,
            "at_utc": row.get("timestamp_utc"),
            "legacy_agent_id": agent_id or None,
            "model_key": keys_by_agent.get(agent_id),
            "orphan": agent_id not in keys_by_agent,
            "model_name_at_the_time": row.get("agent_name"),
            "provider": row.get("provider"),
            "model": row.get("model") or row.get("actual_model"),
            # The role is what the call was made under, back then. Provenance, not a pinning.
            "legacy_role": row.get("role"),
            "legacy_request_role": row.get("request_role"),
            "purpose": row.get("purpose"),
            "status": row.get("status"),
            "error": row.get("error"),
            "input_tokens": row.get("input_tokens"), "output_tokens": row.get("output_tokens"),
            "total_tokens": row.get("total_tokens"),
            "cost_usd": row.get("cost_usd"), "cost_known": row.get("cost_known"),
            "elapsed_sec": row.get("elapsed_sec"),
            "workspace_id": row.get("workspace_id"),
            "origin": {"archive_id": archive_id, "source": "usage"},
        })
    return history


def _provenance(history):
    """Which model actually worked under which old role - stated as history."""
    links = {}
    for row in history:
        role = str(row.get("legacy_role") or "").strip()
        key = row.get("model_key") or row.get("model_name_at_the_time") or "unknown"
        if not role:
            continue
        link = links.setdefault((key, role), {
            "model_key": row.get("model_key"), "model_name_at_the_time": row.get("model_name_at_the_time"),
            "legacy_role": role, "kind": "historical_provenance", "active": False,
            "requests": 0, "ok": 0, "cost_usd": 0.0, "first_at_utc": "", "last_at_utc": ""})
        link["requests"] += 1
        link["ok"] += 1 if row.get("status") == "success" else 0
        link["cost_usd"] = round(link["cost_usd"] + float(row.get("cost_usd") or 0), 8)
        at = str(row.get("at_utc") or "")
        link["first_at_utc"] = min(link["first_at_utc"] or at, at) if at else link["first_at_utc"]
        link["last_at_utc"] = max(link["last_at_utc"], at)
    return sorted(links.values(), key=lambda link: (-link["requests"], link["legacy_role"]))


def _ratings(document, models, archive_id):
    """Ratings migrate only where the rated model can still be named.

    `star_ratings.json` keys its statistics by the model's display name at the
    time. A name that matches a model we migrated is confirmable provenance; a
    name that matches nothing is left in the archive rather than attached to a
    model by guesswork.
    """
    by_name = {str(row.get("name") or ""): row["model_key"] for row in models}
    kept, refused = [], []
    for name, stats in (document.get("model_stats") or {}).items():
        record = {"model_name_at_the_time": name, "model_key": by_name.get(name),
                  "count": stats.get("count"), "avg": stats.get("avg"), "sum": stats.get("sum"),
                  "provider": stats.get("provider"), "updated_at_utc": stats.get("updated_at_utc"),
                  "kind": "historical_rating", "active": False,
                  "origin": {"archive_id": archive_id, "source": "ratings"}}
        (kept if record["model_key"] else refused).append(record)
    for record in refused:
        record["reason"] = "происхождение не подтверждается: такой модели в реестре нет"
    return kept, refused


def migrate(archive_id=None, *, project_root=None):
    """Build the new registry from the archive. Deterministic and repeatable."""
    manifest = legacy_archive.latest(project_root) if archive_id is None else None
    if archive_id is None and not manifest:
        raise RuntimeError("legacy_archive_missing")
    archive = archive_id or manifest["archive_id"]
    checked = legacy_archive.verify(archive, project_root=project_root)
    if not checked["ok"]:
        raise RuntimeError("legacy_archive_drift")

    agents = legacy_archive.agents(archive, project_root=project_root)
    models = _models(agents, archive)
    keys_by_agent = {str(agent.get("id")): model_key(agent) for agent in agents}
    rows = legacy_archive.read_rows(archive, "usage", project_root=project_root)
    history = _history(rows, keys_by_agent, archive)
    provenance = _provenance(history)
    ratings_document = next((legacy_archive.read_json(archive, entry["file"], project_root=project_root)
                             for entry in (legacy_archive._manifest(archive, project_root) or {}).get("files", [])
                             if entry["source"] == "ratings"), {})
    ratings, refused_ratings = _ratings(ratings_document if isinstance(ratings_document, dict) else {}, models, archive)

    root = registry_dir(project_root)
    stamp = _now()
    head = {"schema_version": SCHEMA_VERSION, "source_archive": archive, "migrated_at_utc": stamp}
    _write(root / "models.json", {**head, "models": models})
    _write(root / "provenance.json", {**head, "note": "историческое происхождение, не закрепление", "links": provenance})
    _write(root / "ratings.json", {**head, "ratings": ratings, "not_migrated": refused_ratings})
    path = root / "history.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in history:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary.replace(path)
    return {"archive_id": archive, "models": len(models), "history": len(history),
            "provenance": len(provenance), "ratings": len(ratings), "ratings_not_migrated": len(refused_ratings)}


def reconcile(*, project_root=None):
    """archive -> migration report -> new registry, counted on both sides."""
    root = registry_dir(project_root)
    models = _read(root / "models.json", {}).get("models") or []
    provenance = _read(root / "provenance.json", {}).get("links") or []
    ratings_document = _read(root / "ratings.json", {})
    history = []
    try:
        with (root / "history.jsonl").open("r", encoding="utf-8") as handle:
            history = [json.loads(line) for line in handle if line.strip()]
    except OSError:
        history = []
    archive = (_read(root / "models.json", {}) or {}).get("source_archive")
    checked = legacy_archive.verify(archive, project_root=project_root) if archive else {"ok": False, "drift": []}
    agents = legacy_archive.agents(archive, project_root=project_root) if archive else []
    rows = legacy_archive.read_rows(archive, "usage", project_root=project_root) if archive else []

    # Nothing may be lost: every archived agent and every logged call must be
    # accounted for, either as a migrated fact or as a stated refusal.
    unique_requests = {str(row.get("request_id") or f"row:{index}") for index, row in enumerate(rows)}
    orphans = [row for row in history if row.get("orphan")]
    missing_models = [agent.get("id") for agent in agents
                      if model_key(agent) not in {row["model_key"] for row in models}]
    missing_history = len(unique_requests) - len(history)

    # No migrated model may hold a position, and no old link may be active.
    pinned = [row for row in models if row.get("role") or row.get("purpose") or row.get("team_role")]
    active_links = [link for link in provenance if link.get("active")]

    report = {
        "generated_at_utc": _now(),
        "archive": {"archive_id": archive, "verified": checked.get("ok"), "drift": checked.get("drift", []),
                    "agents": len(agents), "usage_rows": len(rows), "unique_requests": len(unique_requests),
                    "rating_entries": len(ratings_document.get("ratings") or []) + len(ratings_document.get("not_migrated") or [])},
        "migrated_as_history": {"models": len(models), "calls": len(history),
                                "provenance_links": len(provenance),
                                "ratings": len(ratings_document.get("ratings") or [])},
        "not_migrated_on_purpose": [{"field": field, "reason": reason} for field, reason in sorted(NOT_MIGRATED.items())]
                                   + [{"field": "api_key", "reason": "секреты остаются в защищённом хранилище"},
                                      {"field": "star_ratings", "reason": "происхождение не подтверждается",
                                       "count": len(ratings_document.get("not_migrated") or [])}],
        "new_entities": {"registry_files": 4, "agent_roles_created": 0, "model_pins_created": 0},
        "losses": {"models_missing": missing_models, "calls_missing": max(0, missing_history),
                   "orphan_calls": len(orphans)},
        "wrong_pins": {"models_with_a_position": [row["model_key"] for row in pinned],
                       "active_legacy_links": len(active_links)},
    }
    report["ok"] = bool(checked.get("ok")) and not missing_models and missing_history <= 0 \
        and not pinned and not active_links and bool(models)
    _write(root / "migration-report.json", report)
    marker = root / MARKER
    if report["ok"]:
        _write(marker, {"ok": True, "archive_id": archive, "confirmed_at_utc": report["generated_at_utc"],
                        "models": len(models), "calls": len(history)})
    elif marker.exists():
        marker.unlink()
    return report


def state(*, project_root=None):
    """Whether the new registry is the single working registry yet."""
    root = registry_dir(project_root)
    marker = _read(root / MARKER, None)
    report = _read(root / "migration-report.json", None)
    archive = legacy_archive.latest(project_root)
    return {"authoritative": bool(marker and marker.get("ok")),
            "archive_id": (archive or {}).get("archive_id"),
            "frozen_at_utc": (archive or {}).get("frozen_at_utc"),
            "migrated_at_utc": (_read(root / "models.json", {}) or {}).get("migrated_at_utc"),
            "report": report}


def models(*, project_root=None):
    return _read(registry_dir(project_root) / "models.json", {}).get("models") or []


def provenance(*, project_root=None):
    return _read(registry_dir(project_root) / "provenance.json", {}).get("links") or []


def history(limit=200, *, project_root=None):
    path = registry_dir(project_root) / "history.jsonl"
    try:
        with path.open("r", encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
    except (OSError, ValueError):
        return []
    rows.sort(key=lambda row: str(row.get("at_utc") or ""), reverse=True)
    return rows[:max(0, int(limit))]
