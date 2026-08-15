"""Drive one candidate end to end, flushing every step so an interrupted run
leaves a readable trail instead of an empty file."""
import json, sys, time, urllib.error, urllib.request, uuid
ORIGIN = "http://127.0.0.1:8765"

def call(path, body=None, method="GET", timeout=2400.0):
    data = None if body is None else json.dumps(body).encode()
    h = {"Accept": "application/json", "User-Agent": "StratForge-ReleaseButtons/1"}
    if data is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(ORIGIN + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace") if e.fp else ""
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:400]}
    except Exception as e:
        return 0, {"error": type(e).__name__}

def say(*a):
    print(*a); sys.stdout.flush()

def summary(cand):
    s, d = call(f"/api/admin/releases/{cand}")
    return d.get("summary") or {}

version, commit = sys.argv[1], sys.argv[2]
s, created = call("/api/admin/releases/candidates", method="POST", body={
    "app_version": version, "release_channel": "beta",
    "git_commit_sha": commit, "idempotency_key": "btn-" + uuid.uuid4().hex[:20]})
say(f"[create] http={s}")
if s >= 300:
    say(json.dumps(created, ensure_ascii=False)[:500]); raise SystemExit(1)
cand = (created.get("candidate") or created).get("candidate_id") or created.get("candidate_id")
say(f"[create] candidate={cand}")

def act(name, extra=None):
    body = {"idempotency_key": "btn-" + uuid.uuid4().hex[:20]}
    body.update(extra or {})
    st, pl = call(f"/api/admin/releases/{cand}/{name}", body, "POST")
    say(f"[{name}] http={st}" + ("" if st < 300 else " " + json.dumps(pl, ensure_ascii=False)[:400]))
    return st

for step in ("build", "verify", "deploy-canary"):
    if act(step) >= 300:
        say("SUMMARY", json.dumps(summary(cand), ensure_ascii=False)[:400]); raise SystemExit(1)
    time.sleep(2)
say("SUMMARY", json.dumps(summary(cand), ensure_ascii=False)[:400])
say("CANDIDATE " + cand)
