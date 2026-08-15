#!/usr/bin/env python3
"""Dependency check and cleanup of every non-owner account.

Dry run by default. Reports each doomed account's footprint across every
user-keyed store, then (with --apply) removes it through the application's own
delete path so identities, devices, challenges, sessions and workspaces go
with it.

Usage: host_user_cleanup.py <canary|production> <owner_uuid> [--apply]
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

CURRENT = {"canary": "/home/stratforge/canary-current", "production": "/home/stratforge/current"}
PROGRAMS = {"canary": "api", "production": "api-app"}


def load_env(environment: str) -> None:
    out = subprocess.check_output(
        ["sudo", "-n", "supervisorctl", "-c",
         "/home/stratforge/production_data/config/supervisord.conf", "status"],
        text=True, timeout=30,
    )
    pid = 0
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == PROGRAMS[environment] and parts[1] == "RUNNING":
            pid = int(parts[3].rstrip(","))
    if not pid:
        raise SystemExit("api process not running")
    for item in Path(f"/proc/{pid}/environ").read_bytes().split(bytes([0])):
        if not item or b"=" not in item:
            continue
        key, _, value = item.partition(b"=")
        os.environ[key.decode("utf-8", "replace")] = value.decode("utf-8", "replace")


def scan(doc, uuid: str, legacy: int, path: str = "") -> list:
    """Every place in ``doc`` that names this account."""
    hits = []
    if isinstance(doc, dict):
        u = str(doc.get("user_uuid") or doc.get("owner_user_uuid")
                or doc.get("created_by_user_uuid") or "")
        try:
            l = int(doc.get("user_id") or doc.get("owner_user_id")
                    or doc.get("created_by_user_id") or doc.get("legacy_user_id") or 0)
        except (TypeError, ValueError):
            l = 0
        if (uuid and u == uuid) or (legacy and l == legacy):
            hits.append(path or "<root>")
        for k, v in doc.items():
            if isinstance(v, (dict, list)):
                hits.extend(scan(v, uuid, legacy, f"{path}.{k}" if path else k))
            elif k in {str(legacy), uuid} and legacy:
                hits.append(f"{path}[{k}]")
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            hits.extend(scan(v, uuid, legacy, f"{path}[{i}]"))
    return hits


def main() -> int:
    environment, owner_uuid = sys.argv[1], sys.argv[2]
    apply = "--apply" in sys.argv
    load_env(environment)
    sys.path.insert(0, CURRENT[environment])
    from app import account_auth, workspaces
    try:
        from app import subscriptions
    except Exception:
        subscriptions = None
    try:
        from app import user_support
    except Exception:
        user_support = None

    doc = account_auth._read_doc()
    owner = next((u for u in doc["users"]
                  if str(u.get("user_uuid")) == owner_uuid), None)
    if owner is None:
        raise SystemExit(f"canonical owner {owner_uuid} not found -- refusing to touch anything")
    owner_legacy = int(owner.get("user_id") or 0)
    print(f"canonical owner: {owner_uuid} legacy={owner_legacy} "
          f"is_owner={owner.get('is_owner')} status={owner.get('status')}")

    doomed = [u for u in doc["users"] if str(u.get("user_uuid")) != owner_uuid]
    print(f"\n=== DEPENDENCY CHECK: {len(doomed)} account(s) to remove\n")
    for u in doomed:
        uuid = str(u.get("user_uuid"))
        legacy = int(u.get("user_id") or 0)
        print(f"  {uuid}  legacy={legacy}  username={u.get('username') or '-'!r} "
              f"is_owner={u.get('is_owner')}")
        if u.get("is_owner"):
            raise SystemExit("refusing: a second is_owner account is present")
        report = account_auth.account_footprint(owner_legacy, legacy)
        print(f"     auth       : {report['account']}")
        print(f"     workspaces : owned={report['workspaces']['owned_workspaces']} "
              f"shared={report['workspaces']['shared_workspaces']} "
              f"memberships={report['workspaces']['memberships']}")
        for name, mod in (("subscriptions", subscriptions), ("user_support", user_support)):
            if mod is None:
                continue
            try:
                other = mod._read_doc() if hasattr(mod, "_read_doc") else mod._load()
            except Exception as exc:
                print(f"     {name:11}: unreadable ({type(exc).__name__})")
                continue
            hits = scan(other, uuid, legacy)
            print(f"     {name:11}: {len(hits)} reference(s) {hits[:6]}")
        print(f"     safe_to_delete={report['safe_to_delete']}")

    if not apply:
        print("\nDRY RUN -- nothing changed. Re-run with --apply.")
        return 0

    print("\n=== APPLY\n")
    for u in list(doomed):
        legacy = int(u.get("user_id") or 0)
        uuid = str(u.get("user_uuid"))
        if user_support is not None:
            try:
                user_support.purge_user(owner_legacy, legacy)
            except Exception as exc:
                print(f"  user_support purge {legacy}: {type(exc).__name__}: {exc}")
        account_auth.delete_user(owner_legacy, legacy)
        print(f"  deleted {uuid} (legacy {legacy})")

    after = account_auth._read_doc()
    print("\n=== AFTER")
    print(f"  users={len(after.get('users') or [])} "
          f"identities={len(after.get('auth_identities') or [])} "
          f"sessions={len(after.get('sessions') or [])} "
          f"devices={len(after.get('trusted_devices') or [])} "
          f"security_challenges={len(after.get('security_challenges') or [])}")
    for u in after.get("users") or []:
        print(f"  remaining: {u.get('user_uuid')} legacy={u.get('user_id')} "
              f"is_owner={u.get('is_owner')} username={u.get('username')!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
