"""
recover_stale_jobs.py

Recover stale running jobs/batches without manually moving folders.

Two modes:

  default (cancel mode):
      1. Walk jobs/running/ — find folders whose newest file mtime is older
         than --stale-secs (default 600s).
      2. POST /api/jobs/<id>/cancel (or /api/batches/<id>/cancel).
      3. Wait --wait-after-cancel seconds, re-check.
      4. Report any stragglers (does NOT move folders).
      Requires the backend HTTP server to be reachable.

  --finalize:
      Reapplies the bridge's own promotion rules locally, without ever
      touching folders manually. For each running/<id>:
        - if result.json has `finished_at_utc`        -> done/
        - elif error.json  has `finished_at_utc`      -> failed/
        - elif cancel.flag and heartbeat is stale     -> cancelled/
      Pure os.replace + shutil.move. No HTTP required. Use this when the
      bridge / NinjaTrader has actually crashed and cancel is moot.

Usage:
    python recover_stale_jobs.py                     # cancel mode, dry list
    python recover_stale_jobs.py --finalize          # finalize, dry-run
    python recover_stale_jobs.py --finalize --apply  # finalize, do moves
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
JOBS_RUNNING = os.path.join(ROOT, "jobs", "running")


def _newest_mtime(path: str) -> float:
    newest = 0.0
    for r, _d, files in os.walk(path):
        for fn in files:
            try:
                m = os.path.getmtime(os.path.join(r, fn))
                if m > newest:
                    newest = m
            except OSError:
                pass
    return newest


def _post_cancel(server: str, kind: str, jid: str) -> tuple[bool, str]:
    url = f"{server.rstrip('/')}/api/{kind}/{jid}/cancel"
    req = urllib.request.Request(url, data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return (r.status < 400, r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        return (False, f"HTTP {e.code}: {e.read().decode('utf-8','ignore')}")
    except Exception as e:
        return (False, str(e))


def _read_json_safe(p):
    try:
        with open(p, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _heartbeat_age_s(jdir: str) -> float | None:
    hb = _read_json_safe(os.path.join(jdir, "heartbeat.json")) or {}
    ts = hb.get("updated_at_utc")
    if ts:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - dt).total_seconds()
        except ValueError:
            pass
    try:
        return time.time() - os.path.getmtime(jdir)
    except OSError:
        return None


def _safe_move(src: str, dst_dir: str, *, apply: bool) -> tuple[bool, str]:
    name = os.path.basename(src)
    dst = os.path.join(dst_dir, name)
    if os.path.exists(dst):
        return (False, f"target_exists:{dst}")
    if not apply:
        return (True, f"WOULD_MOVE -> {dst}")
    os.makedirs(dst_dir, exist_ok=True)
    shutil.move(src, dst)
    return (True, f"MOVED -> {dst}")


def finalize_running(stale_secs: float, apply: bool) -> int:
    """Move running/<id> entries to done/failed/cancelled per their artifacts.

    Mirrors the bridge's own promotion rules — purely local, no HTTP.
    """
    if not os.path.isdir(JOBS_RUNNING):
        print(f"[ok] no running dir at {JOBS_RUNNING}")
        return 0

    done = os.path.join(ROOT, "jobs", "done")
    failed = os.path.join(ROOT, "jobs", "failed")
    cancelled = os.path.join(ROOT, "jobs", "cancelled")
    n_done = n_failed = n_cancelled = n_orphan = n_live = 0

    print(f"[finalize] mode={'APPLY' if apply else 'DRY-RUN'} hang>{stale_secs}s")
    for name in sorted(os.listdir(JOBS_RUNNING)):
        jdir = os.path.join(JOBS_RUNNING, name)
        if not os.path.isdir(jdir) or name.startswith("."):
            continue
        result = _read_json_safe(os.path.join(jdir, "result.json"))
        error  = _read_json_safe(os.path.join(jdir, "error.json"))
        cflag  = os.path.isfile(os.path.join(jdir, "cancel.flag"))
        hb_age = _heartbeat_age_s(jdir)

        if isinstance(result, dict) and result.get("finished_at_utc"):
            ok, msg = _safe_move(jdir, done, apply=apply)
            n_done += 1
            print(f"  done  : {name} hb={int(hb_age) if hb_age else '—'}s  {msg}")
            continue
        if isinstance(error, dict) and error.get("finished_at_utc"):
            ok, msg = _safe_move(jdir, failed, apply=apply)
            n_failed += 1
            print(f"  failed: {name} hb={int(hb_age) if hb_age else '—'}s  {msg}")
            continue
        if cflag and (hb_age is None or hb_age > stale_secs):
            ok, msg = _safe_move(jdir, cancelled, apply=apply)
            n_cancelled += 1
            print(f"  cancel: {name} hb={int(hb_age) if hb_age else '—'}s  {msg}")
            continue
        if hb_age is not None and hb_age > stale_secs:
            n_orphan += 1
            print(f"  ORPHAN: {name} hb={int(hb_age)}s — manual review")
            continue
        n_live += 1
        print(f"  live  : {name} hb={int(hb_age) if hb_age else '—'}s")

    print(f"[finalize] done+={n_done} failed+={n_failed} "
          f"cancelled+={n_cancelled} orphan={n_orphan} live={n_live} "
          f"applied={apply}")
    return 0 if n_orphan == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stale-secs", type=int, default=600)
    ap.add_argument("--server", default="http://127.0.0.1:8765")
    ap.add_argument("--wait-after-cancel", type=int, default=20)
    ap.add_argument("--finalize", action="store_true",
                    help="Skip HTTP cancel; finalize folders by their artifacts.")
    ap.add_argument("--apply", action="store_true",
                    help="With --finalize, perform moves (default: dry-run).")
    args = ap.parse_args()

    if args.finalize:
        return finalize_running(stale_secs=args.stale_secs, apply=args.apply)

    if not os.path.isdir(JOBS_RUNNING):
        print(f"[ok] no running dir at {JOBS_RUNNING}")
        return 0

    now = time.time()
    folders = sorted(os.listdir(JOBS_RUNNING))
    if not folders:
        print("[ok] queue clean — no running jobs")
        return 0

    stale = []
    for name in folders:
        full = os.path.join(JOBS_RUNNING, name)
        if not os.path.isdir(full):
            continue
        mt = _newest_mtime(full) or os.path.getmtime(full)
        age = now - mt
        if age >= args.stale_secs:
            stale.append((name, age))

    if not stale:
        print(f"[ok] {len(folders)} running, none stale (>={args.stale_secs}s)")
        return 0

    print(f"[stale] found {len(stale)} stale entries:")
    for name, age in stale:
        kind = "batches" if name.startswith("batch_") and "__" not in name else "jobs"
        print(f"  - {name} (age={int(age)}s, kind={kind})")
        ok, body = _post_cancel(args.server, kind, name)
        print(f"    cancel -> ok={ok} body={body[:200]}")

    print(f"[wait] sleeping {args.wait_after_cancel}s before re-check...")
    time.sleep(args.wait_after_cancel)

    still = [n for n in os.listdir(JOBS_RUNNING)
             if os.path.isdir(os.path.join(JOBS_RUNNING, n))]
    rep = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "stale_secs": args.stale_secs,
        "stale_found": [n for n, _ in stale],
        "still_running_after_cancel": [n for n in still
                                       if n in {x for x, _ in stale}],
    }
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0 if not rep["still_running_after_cancel"] else 1


if __name__ == "__main__":
    sys.exit(main())
