# 14. External GPT Operating Instructions

- Context Pack document: 14_EXTERNAL_GPT_OPERATING_INSTRUCTIONS.md
- Last verified UTC: 2026-08-13T02:25:57Z
- Verified against Git SHA: cad53f682e413db86bc3a77e57f8942baf4d4bc3
- Scope: How an external GPT should reason and ask for extra files when using this pack
- Status: DONE

## Operating rules

1. Treat this Context Pack as your primary project context.
2. Treat [02_CURRENT_SYSTEM_STATE.md](02_CURRENT_SYSTEM_STATE.md) and
   [11_ACTIVE_WORK_AND_HANDOFF.md](11_ACTIVE_WORK_AND_HANDOFF.md) as the highest-priority current-state files.
3. Do not present an old plan or old audit as current state when newer code,
   schema or current docs contradict it.
4. Distinguish clearly between `Fact`, `Inference` and `Proposal` in your own reasoning.
5. Do not treat `PARTIAL` as a successful release or operational acceptance.
6. Assume you have **no** direct access to GitHub, local files, servers,
   deployment consoles, databases or secrets beyond what the owner uploads.
7. Never invent secrets, token values, local paths, env contents, deployed build
   numbers or legal decisions that are not in the uploaded material.

## When you need more files

- Ask only for the smallest source slice needed for the task.
- For code review, ask for the exact diff or source files in the affected
  subsystem, not the whole repository.
- For auth/security/release work, ask for the specific module or migration named
  in [12_API_AND_SCHEMA_REFERENCE.md](12_API_AND_SCHEMA_REFERENCE.md).

## Response discipline

- If a current deployed artifact/version is not proven by this pack, say so.
- If a feature is gated or blocked, say `EXTERNAL BLOCKED` or `PARTIAL`; do not
  upgrade it to released just because code exists.
- If recommending a change, always state affected subsystem, risk, test impact
  and release impact.
- Separate owner/counsel/ops decisions from pure engineering facts.

## Priority order for conflicts

1. Current code/schema/config evidence referenced by this pack.
2. Current canonical docs and ADRs.
3. Historical plans, audits and handoffs only as background.

## Safe default requests

- `app/server.py` for route/control-path questions.
- `app/runtime_env.py` for environment/release questions.
- `app/account_auth.py`, `app/auth_identity.py`, `app/security_devices.py` for auth/security.
- `app/connector_protocol.py`, `app/market_data_failover.py` for Connector/market data.
- `app/release_center.py`, `app/blue_green.py` for release/deployment.
- the relevant doc in `docs/adr/`, `docs/architecture/` or this pack for contract clarification.