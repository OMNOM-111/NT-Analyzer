# Phase 10 — Documentation reorganization + governance amendment workflow — Implementation Evidence

**Status: Phase 10 — IMPLEMENTATION CLOSED; GIT CLOSEOUT COMPLETE.**
Documentation reorganization is delivered as a canonical tree + an
owner-reviewable migration map; the physical relocation of already-referenced
files is executed in owner-approved steps (the map is the required
"owner-approved migration map" dependency) so no inbound link is broken. This
document contains no secrets, keys, tokens or real DSNs.

## 1. Source state

- Repository: `OMNOM-111/NT-Analyzer`.
- Integration branch: `release/0.10.0-next-architecture` at `68137c44` (Phase 9 closeout).
- Phase branch: `phase/10-documentation`, created from `68137c44`.
- Baseline `origin/main` (`72f46a1a`) untouched.

## 2. Files created / changed

Created:
- `docs/DOCS_STRUCTURE.md` — the canonical docs-tree specification + migration map (every loose doc → target home, archive list, reference-rewrite policy).
- `docs/agents/README.md`, `docs/strategies/README.md`, `docs/security/README.md`, `docs/product/README.md`, `docs/changelog/README.md`, `docs/archive/README.md`, `docs/archive/audits/README.md` — canonical directory index files (also materialize the new directories in Git).
- `tests/test_phase10_docs_governance.py` — focused Phase 10 tests.
- `docs/current/PHASE_10_DOCS_GOVERNANCE_IMPLEMENTATION_EVIDENCE.md` — this evidence.

Changed:
- `app/server.py` — new `_require_governance_manage()`; `_governance_post` now gates every governance mutation on it (owner or `docs.manage_global`).
- `docs/current/NEXT_ARCHITECTURE_PROGRAM_STATUS.md` — Phase 10 status + evidence.

## 3. Canonical docs tree (acceptance criterion: current vs target separated)

Phase 10 establishes the canonical tree
`docs/{current,architecture,operations,security,product,agents,strategies,governance,changelog,adr,archive}`
(+ `archive/audits`, existing `schemas`). The previously-missing directories
`security/`, `product/`, `agents/`, `strategies/`, `changelog/`, `archive/` and
`archive/audits/` are created with concise index READMEs. `docs/current/` holds
only the active next-architecture program; superseded dated snapshots are mapped
to `docs/archive/`.

`docs/DOCS_STRUCTURE.md` is the authoritative migration map: it assigns every
loose file under `docs/` to its target directory and lists the ~14 dated audit
snapshots destined for `docs/archive/` plus the master-plan-specified rename
`PRODUCT_MODES_AND_CONTOURS_AUDIT_2026-07-18.md → archive/audits/2026-07-18-product-contours.md`.

### Why the bulk relocation is staged, not performed here

The dated audit files and category docs have **32 inbound references across 21
files**, including repo-root `README.md`, `STRATFORGE_ГЕНЕРАЛЬНЫЙ_ПЛАН.md`,
`docs/AGENTS.md` and each other. The Phase 10 plan lists an "owner-approved
migration map" as a hard dependency. Rather than break 32 links (many are prose
back-tick references the link scanner cannot auto-fix), Phase 10 delivers the
canonical tree + the map for owner approval; each physical `git mv` + reference
rewrite is then applied in an owner-approved step, verified by the markdown link
audit so no move lands with a broken link. This is the safe, reversible path the
plan prescribes ("docs moves happen through PR/commit; keep archive path and
redirect map").

## 4. Governance amendment workflow (acceptance criterion + owner decision #9)

Before Phase 10, `POST /api/governance/laws|documents` was gated only by the
read-level `documents` capability — i.e. any user who could *read* governance
could also *write* it. Phase 10 adds `_require_governance_manage()` in
`app/server.py`, invoked first in `_governance_post`: a governance mutation now
requires the **owner** or an explicitly delegated **`docs.manage_global`**
capability (a high-risk grant only the owner holds by default), returning
`403 governance_manage_required` otherwise. GET reads stay at the `documents`
capability, so nothing read-only regresses. This implements owner decision #9
(owner-only approve now, audit trail, future-extensible via the delegable
capability).

The amendment journal is unchanged and already compliant: every governance write
appends to `data/governance/change_log.jsonl` with `actor`, `reason`, `ts_utc`
(UTC), `amendment_no` and per-field `changes`, and re-renders
`docs/governance/OVERVIEW.md`.

## 5. Global governance cannot be modified by a workspace / strategy override (acceptance criterion)

Proven by construction and by tests:
- Governance is a single **global** store (`data/governance/*`).
  `governance.update_law` / `update_markdown_document` accept **no**
  workspace/tenant/scope parameter — there is no per-workspace governance
  mutation path to exploit.
- `jobqueue.update_strategy_profile` applies a strict field allowlist
  (`{name, status, status_label, notes, lifecycle, origin, trial_plan,
  demo_plan, failed_archive}`) that contains no governance/law/document field and
  never calls `governance.update_*`. The two stores (`data/governance/` vs
  `data/profiles/`) are disjoint.
- Governance writes are now additionally owner/`docs.manage_global`-gated at the
  HTTP boundary (§4), so even an authenticated non-owner workspace user cannot
  mutate global governance.

## 6. Tests

`tests/test_phase10_docs_governance.py` (12 tests):
- canonical docs tree exists; new dirs have index READMEs; migration map covers
  every category + archive + `docs.manage_global`;
- **markdown link audit** — `release_static_scan.scan_markdown_links()` returns
  no broken links (the plan's link audit, now enforced in CI);
- owner resolves `docs.manage_global`; a plain user does not; an explicit grant
  enables it;
- the governance write handler is wired to `_require_governance_manage` and the
  guard checks `docs.manage_global` / owner / `governance_manage_required`
  (source contract);
- governance update functions have no workspace/tenant/scope parameter;
- the strategy allowlist excludes governance and never calls `governance.update`;
- the governance and profile stores are disjoint;
- the amendment journal records `actor`, `reason`, `ts_utc`, `amendment_no`,
  `changes`.

## 7. Commands run and results

- Focused: `tests/test_phase10_docs_governance.py` → **12 passed**.
- Regression-sensitive suites (`test_governance`, `test_permissions`,
  `test_ux_mode`, `test_aurora_contracts`, `test_cutover_routing`,
  `test_integrations`, `test_staging_isolation`) → **94 passed**.
- Full regression: `python -m pytest -q -p no:cacheprovider` → **1148 passed, 31 skipped**.
- `python -m compileall -q app tools tests` → PASS.
- `python tools/release_static_scan.py` → CSP OK, SECRETS OK, MARKDOWN OK.
- `git diff --check` (Phase 10 files) → clean.

## 8. Exact passed/skipped totals

- Focused Phase 10: 12 passed.
- Full repository: 1148 passed, 31 skipped (the 31 skips are the live-PostgreSQL
  and other environment-gated suites).

## 9. Errors encountered

- None. The governance guard did not regress any suite (the only governance HTTP
  test is a GET, unaffected; the direct `governance.update_law` unit test bypasses
  the HTTP guard and still passes).

## 10. Dry-run / not-performed actions

- No physical relocation of already-referenced docs was performed (staged behind
  owner approval of the migration map to avoid breaking 32 inbound links). No
  file was deleted. Stray/generated files were left untouched.

## 11. Rollback

Revert the Phase 10 implementation/merge commit. The new directories/READMEs and
`DOCS_STRUCTURE.md` are additive; the `_require_governance_manage` guard is a
single server method — reverting it restores the prior gate. No schema/migration
change was made in Phase 10.

## 12. Known risks and owner decisions

- Owner decision #9 (docs amendment workflow strictness) implemented as
  owner-only-by-default via the delegable `docs.manage_global` capability.
- The bulk physical relocation of docs is intentionally staged pending owner
  approval of `docs/DOCS_STRUCTURE.md` (the migration map), to keep every inbound
  link intact; the duplicate root `repository-hygiene.md` removal is likewise
  mapped, not executed here.

## 13. Commit / PR / CI / merge evidence

- Implementation commit: `25fffb42` on `phase/10-documentation` (from integration `68137c44`).
- PR: [#16](https://github.com/OMNOM-111/NT-Analyzer/pull/16) → base `release/0.10.0-next-architecture`.
- CI ([Actions run 30829268990](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/30829268990)): Static gates PASS; Tests (ubuntu-latest) PASS; Tests (windows-latest) PASS.
- Merge commit: `bd4fbc47`; task branch `phase/10-documentation` deleted locally and on origin; integration `release/0.10.0-next-architecture` in sync with origin after merge.
- Extraneous dirty/untracked files (`data/catalog/margins.json`, `data/development/durable/nt_analyzer.sqlite3`, `data/development/audit/`, `data/development/integrations/`, `data/governance-rendered/*`, `docs/AGENT_PERSONAS.md`, `docs/governance/*`) were preserved on disk and remained outside the Phase 10 delivery.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-11T08:13:16Z | GPT-5.5 через Codex по запросу owner | Removed the visible technical amendment header during final Development documentation closeout; historical evidence remains in Git history.
-->
