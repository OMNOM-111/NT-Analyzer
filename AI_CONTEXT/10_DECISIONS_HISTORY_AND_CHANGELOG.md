# 10. Decisions History and Changelog

- Context Pack document: 10_DECISIONS_HISTORY_AND_CHANGELOG.md
- Last verified UTC: 2026-10-01T01:27:27Z
- Verified against Git SHA: e7ecd2133c65f7ec6ce2bf8dc02eb797819ea885
- Scope: High-value milestones and architectural decisions only
- Status: DONE

## Milestones that still matter today

| Date | Decision / milestone | Why it mattered | Current or superseded |
| --- | --- | --- | --- |
| 2026-07-01 | Optional cloud-agent fallback was researched and constrained instead of becoming the default control plane | preserved a local-first posture and kept provider usage budgeted and explicit | current principle; historical benchmark docs are archived |
| 2026-07-16 | Market-data baseline was normalized around TopstepX-first read-only charts, explicit provenance and no synthetic candles | separated chart-source logic from execution authority | current |
| 2026-07-28 | Stage 9 handoff documented canary server deployment and Windows Connector acceptance steps | created operational evidence for release/deploy workflow | historical evidence, not proof of current live deployment |
| 2026-08-01 | ADR-0001 split deployment environment from release channel | stopped conflating `dev/beta/stable` with `development/canary/production` | current |
| 2026-08-01 | ADR-0002 adopted UUID internal identity with provider mappings | made Telegram/Google/email linkable without using Telegram numeric ID as the long-term primary key | current |
| 2026-08-01 | ADR-0003 defined trusted devices and step-up | moved critical actions toward explicit device and action-bound confirmation | current, implementation still partial |
| 2026-08-01 | ADR-0004 defined admin capabilities and a separate Admin Panel boundary | made server-side capability checks primary and UI hiding secondary | current, UI maturity still partial |
| 2026-08-01 | ADR-0005 fixed immutable release promotion as the target model | established `clean commit -> signed artifact -> canary -> same artifact -> production` | current |
| 2026-08-10 | user-facing legal package was created as DRAFT only | gave the repo a concrete legal surface without pretending it was already published | current DRAFT |
| 2026-08-11 | public version metadata moved to `0.10.0-beta.1` and README current-state wording was aligned around TopstepX-first charts and NinjaTrader execution authority | reduced drift between top-level product docs and actual current contracts | current |
| 2026-08-12 | Auth/DEV fix shipped as signed artifact `795db0c1` and restored Sign in/Register plus local DEV owner flow | converted a reopened owner-acceptance failure into a real operational release artifact | superseded by the later hang-fix release, but still the direct previous slot |
| 2026-08-12 | `/ready` hang was fixed in signed artifact `6b6dc458` and the exact same release directory was accepted on Canary then Production | proved the live promotion path, bounded readiness probes and environment switch behavior | historical; superseded by beta.29 |
| 2026-08-13 | External GPT Context Pack introduced | created a compact, updateable handoff surface for external LLM projects with no repo access | current |
| 2026-08-13 | Final hardening artifact `7ebda6fa` completed mission-led Documents UI closeout, real Release Center Canary deploy, rollback/re-promote and clean-SHA chart acceptance | proved the owner-facing Canary workflow and preserved the TopstepX marker baseline while leaving Production unchanged | historical evidence |
| 2026-08-23 | Beta.29 merge `4d15f1d` completed scoped market-data fan-out fixes and application responsive acceptance, then one signed artifact passed Canary and was promoted unchanged to Production | proved single-hub/multi-client chart behavior, honest stale/live marker semantics, byte-identical UI and the complete current release path | current operational baseline |

## What this history replaces

- Older audits that still describe Telegram numeric ID as the only identity key
  are superseded by current schema and code.
- Older environment descriptions that mix `canary` with release channel labels are
  superseded by ADR-0001 and `README-RUN-MODES.md`.
- Older statements that “the current live build is unknown from the repo” are
  superseded by the canonical beta.29 operational release snapshot.
- Older market-data stories that imply charts follow NinjaTrader uptime are
  superseded by the TopstepX-first read-only baseline.

## Canonical evidence

- [../adr/README.md](../NT-Analyzer/docs/adr/README.md)
- [../adr/0001-environments-and-release-identity.md](../NT-Analyzer/docs/adr/0001-environments-and-release-identity.md)
- [../adr/0002-unified-identity.md](../NT-Analyzer/docs/adr/0002-unified-identity.md)
- [../adr/0003-trusted-devices-and-step-up.md](../NT-Analyzer/docs/adr/0003-trusted-devices-and-step-up.md)
- [../adr/0004-admin-panel-and-capabilities.md](../NT-Analyzer/docs/adr/0004-admin-panel-and-capabilities.md)
- [../adr/0005-immutable-release-promotion.md](../NT-Analyzer/docs/adr/0005-immutable-release-promotion.md)
- [../../ANTIGRAVITY_STAGE9_HANDOFF.md](../NT-Analyzer/ANTIGRAVITY_STAGE9_HANDOFF.md)
- [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../NT-Analyzer/docs/changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md)
- [../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md](../NT-Analyzer/docs/changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md)
- [../changelog/2026-08-22-market-data-responsive-release-beta29.md](../NT-Analyzer/docs/changelog/2026-08-22-market-data-responsive-release-beta29.md)
- [../legal/README.md](../NT-Analyzer/docs/legal/README.md)
