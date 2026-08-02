# Next Architecture Program Status

История поправки: 2026-08-02T01:55:27Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: Phase 1 — зафиксировать реализацию environment metadata, build identity, visual marking и evidence.

История поправки: 2026-08-02T00:53:55Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: Phase 0 — создать единый журнал выполнения Phase 0–10.

Обновлено: 2026-08-02T01:55:27Z

## Baseline

- Repository: `OMNOM-111/NT-Analyzer`
- Baseline: `72f46a1a3a1d32051a00d087808755676ec4d992`
- Baseline branch: `main`; при старте `HEAD == origin/main`, working tree clean
- Version at baseline: `0.9.0-dev.10`
- Release history: Git tags on non-baseline history reach `stratforge-server-v0.9.0-dev.15`; the next minor line avoids reusing any `0.9.0-dev.N` identifier
- Next version: `0.10.0-dev.1`
- Integration branch: `release/0.10.0-next-architecture`
- Production/Canary boundary: deployment, Production DB/secrets, DNS/Cloudflare и реальные bot/email credentials вне scope

## Сводка

| Phase | Status | Branch | Commit/PR | Ключевой результат |
|---|---|---|---|---|
| 0 | STAGE CLOSED | merged/deleted | `fe38c3b7`; [PR #6](https://github.com/OMNOM-111/NT-Analyzer/pull/6) | Принятые решения зафиксированы в ADR; CI PASS |
| 1 | IMPLEMENTATION COMPLETE; GIT CLOSEOUT PENDING | `phase/1-environment-metadata` | PR pending | Environment metadata, version, badges, owner icons |
| 2 | PENDING | `phase/2-admin-panel` | pending | Admin Panel и capabilities |
| 3 | PENDING | `phase/3-unified-identity` | pending | UUID identity и provider abstraction |
| 4 | PENDING | `phase/4-trusted-devices` | pending | Devices и step-up |
| 5 | PENDING | `phase/5-personal-nt-security` | pending | Personal NT security |
| 6 | PENDING | `phase/6-agent-resource-queue` | pending | Agent allocation и NT lease |
| 7 | PENDING | `phase/7-canary-environment` | pending | Canary config без deployment |
| 8 | PENDING | `phase/8-release-center` | pending | Release Center |
| 9 | PENDING | `phase/9-blue-green` | pending | Blue-green tooling без deployment |
| 10 | PENDING | `phase/10-documentation` | pending | Canonical docs и amendment workflow |

## Phase 0 evidence

- Components: `docs/adr/*`, `docs/architecture/NEXT_ARCHITECTURE_OVERVIEW.md`, этот program status, governance change log и `.github/workflows/next-architecture-ci.yml`.
- Tests: `release_static_scan.py --scan markdown` — PASS; `--scan secrets` — PASS; targeted regression — `154 passed, 20 skipped`.
- CI: Ubuntu static gates PASS; Ubuntu tests PASS; Windows tests PASS; Actions run `30726953570`.
- Migrations: none.
- Risks: ADR может разойтись с runtime, если последующие phases обойдут acceptance tests.
- Rollback: revert documentation commit; runtime rollback не требуется.
- Remaining dependencies: последовательная реализация Phase 1–10; реальные email/bot credentials и deployment остаются owner gates.
- Environment impact: Development/Canary/Production behavior unchanged.

## Phase 1 evidence

- Components: `app/runtime_env.py`, server/runtime API, local launchers, immutable server release manifest/verifier, Production env template, Aurora shell/mode-entry UI, три owner icon assets.
- Runtime contract: `DEPLOYMENT_ENV=development|canary|production`; `RELEASE_CHANNEL=dev|beta|stable`; `APP_VERSION`, `BUILD_ID`, `GIT_COMMIT_SHA`, `ARTIFACT_SHA256`, `BUILD_TIMESTAMP_UTC`, `dirty` доступны через `/api/runtime/env`.
- Isolation: Canary имеет отдельный обязательный `STRATFORGE_CANARY_DATA_ROOT`; пересечение Development/Canary/Production roots и dirty remote build отклоняются.
- Visual contract: `DEV`, `CANARY`, `BETA`; stable Production без `STABLE`; favicon и внутренний mark выбираются по environment/channel.
- Local tests: focused `75 passed`; full regression `889 passed, 31 skipped`; PowerShell parse, `node --check`, `py_compile` — PASS.
- Static gates: CSP PASS; SECRETS PASS; MARKDOWN PASS.
- CI/PR: pending.
- Migrations: none.
- Rollback: revert Phase 1 commit; schema rollback не требуется.
- Environment impact: изменён только код и Development metadata; Canary/Production deployment, secrets, DNS, DB и реальные bot/email credentials не затронуты.
