# Agent World — Persona execution and live state continuity

Status: **IN DEVELOPMENT**, not release/owner acceptance. Version remains
`0.10.0-beta.96`. Task branch `codex/agent-world-unified-acceptance`, draft
[PR #285](https://github.com/OMNOM-111/NT-Analyzer/pull/285).
Parent executable checkpoint: `e45b64b0121014c5d796553ae8b512d98a5782ae`.
Exact new source will be recorded after this checkpoint is preserved; do not
substitute the parent's full/PG result for verification of this delta.

## Change and evidence

- The full-Aurora browser exposed a correctly selected Persona rejected by
  Execution V2. `_request` now retains the optional `persona_selection` used
  by ModelService's approved-request digest. Legacy absent-selection requests
  remain unchanged. The actual-V2 positive test and revision/id/removal tamper
  tests keep the integrity guard, not a bypass. Persona suite: 24 PASS.
- Overview, Work and read-only Task/Agent inspectors refresh from existing
  scoped GET APIs through Aurora's existing polling lifecycle. No new jobs,
  permissions, acceptance, retries or feature flag activation. Already loaded
  pages are reread with bounded existing cursors; forms, text selection, audio,
  focus, scroll and expanded details are preserved. Mid-request interaction
  and errors are checked again; denied access/scope changes still fail closed.
- The existing Work table retains horizontal scrolling with readable minimum
  widths for stage/status/time cells; no full relayout or change to design plan.
- SF Chat gives a plain-language failure, with only allowlisted diagnostic
  codes/HTTP status in expandable details. Arbitrary provider payloads/secrets
  are not rendered. Ambiguous delivery explicitly asks to reread history;
  no automatic second POST is introduced. Historical data is not rewritten.
- Closed shared drawers are inert and hidden from accessibility navigation,
  with a generation check preventing a queued open frame from reopening them.
  Reopening restores interactivity and current heading. All Aurora pages share
  the exact updated UI asset query; API and other shared assets stay unchanged.

The initial 211-test bounded run passed before the subsequent race/inert/error
corrections. Final focused rerun: **294 PASS**, 156.94 s (live refresh, Persona
identity/Chat handlers, actual Persona/V2 execution, Execution V2, Aurora/cache,
SF Chat dialogs). Python and Node syntax, root CSP/SECRETS/MARKDOWN,
External GPT Context and staged diff checks passed. The Context validator keeps
the existing historical verification-anchor warning.
The first 595-file pre-release bundle rejected a link to a deliberately
unshipped developer current-document; the receipt now names that exclusion
without a shipped hyperlink. Corrected **595-file pre-release bundle: PASS**
(bundle static scan, shipped runtime reads, Python compilation, JavaScript
syntax). No accepted-exclusion workaround changes the artifact's file list.
Initial harness failures were a missing `detailTab` fixture and a cross-VM array
prototype mismatch; neither justified weakening product assertions.

## Verification boundary and continuation

- The [e45 verification receipt](2026-09-09-agent-world-e45-verification.md)
  holds the separately completed full 5416 PASS/119 SKIP, legacy 13/13, fresh
  PostgreSQL 69+41+7 and actual PG runtime/restart/RLS evidence.
- New-code browser and full immutable regression remain pending at preservation.
  Continue the complete program, not only this presentation correction.
- New executable/storage behavior, endpoint permissions, budgets and feature
  flags are not enabled in protected environments by this change. Existing
  test executor remains development-only, exact-workspace, synthetic, no real
  provider call and no model-quality claim.
- Protected owner Local8765 is unchanged. Only the isolated8804 data/code may
  be backed up and relaunched; preserve the retained error/result history.
- Rollback source: parent e45 plus the cold synthetic-data backup created
  before testing this delta. Do not copy rollback data over newer history.
- Owner registration/consent, own test key, permanent real Social publication
  and visual design acceptance remain separate pending owner actions. Real
  NinjaTrader/provider results cannot be replaced by fixtures or a PNG.
- No merge, deploy, real orders, paid calls, working-DB migrations or secrets
  copying. Nothing is published to Canary or Production.
