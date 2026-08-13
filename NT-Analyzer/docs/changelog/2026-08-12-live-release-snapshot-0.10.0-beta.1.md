# Live release snapshot — 0.10.0-beta.1 / 6b6dc458

Дата operational acceptance: 2026-08-12

Этот документ фиксирует **operational evidence** последнего подтверждённого
release/deployment closeout. Он дополняет repository evidence из кода, схем,
ADR и deploy templates, но не подменяет его.

## Evidence types

- **Repository evidence** — что текущий репозиторий реализует и какие контракты
  задают код/схема/config/docs.
- **Operational evidence** — что было подтверждено последним accepted
  release/deployment closeout на реальных DEV/CANARY/PRODUCTION контурах.
- Если repository evidence и operational evidence отвечают на разные вопросы,
  это нужно проговаривать явно, а не склеивать в один псевдо-факт.

Часть operational полей ниже не выводится напрямую из репозитория и сохранена
здесь именно как canonical closeout record, чтобы не зависеть от chat history.

## Release identity

| Field | Value |
| --- | --- |
| Product version | `0.10.0-beta.1` |
| Artifact git SHA | `6b6dc4589407855526cf6cc345376d64cf95200e` |
| Build ID | `sf-0.10.0-beta.1-6b6dc4589407-20260812T232811Z` |
| Manifest SHA256 | `272045DB15D98C8505D770BAC9389215FD90E9C70F0BB14C19CEABABD31BD9F3` |
| Archive SHA256 | `3EF790F05A24BC4EB7A9DFAD343F7284E0A61F832A1A3B8392C815E7C59E6730` |
| Signing fingerprint | `SHA256:93f0831642bc403dcb780f96180d01a86a8c7adf1cbb0368a0aaa915441e6e64` |
| Release path | `6b6dc458 -> signed immutable artifact -> CANARY -> acceptance -> same release directory/artifact -> PRODUCTION` |
| `same_release_dir` | `true` |
| Previous / one-step rollback slot | `0.10.0-beta.1-795db0c1` |

## Environment snapshot

| Environment | Identity | Operational state |
| --- | --- | --- |
| DEV | `http://127.0.0.1:8765/ui/`, `[DEV]`, `deployment_environment=development`, `config_profile=local-development`, local owner session | app identity `6b6dc458`, `dirty=false`, Production data not used |
| CANARY | `https://canary.stratforges.com`, `[CANARY]`, `deployment_environment=canary`, `instance=stratforge-canary-01`, `config_profile=production-canary`, DB `stratforge_canary` | same git/build/artifact as Production; worker topology `api / worker-canary / operations-canary`; readiness fixed and fast; Telegram `PARTIAL: disabled_pending_canary_bot_provisioning` |
| PRODUCTION | `https://app.stratforges.com`, `[BETA]`, `deployment_environment=production`, `instance=stratforge-linux-production-01`, `config_profile=production-primary`, DB `stratforge_production` | same git/build/artifact as Canary; Supervisor `api-app / worker / operations / telegram`; `previous` = `0.10.0-beta.1-795db0c1` |

Note: deploy templates and tests still use generic Production example values such
as `stratforge-prod-01`; the exact live Production instance label above is
operational closeout evidence, not a template default.

## Readiness defect and fix

| Area | Operational evidence |
| --- | --- |
| Root cause | Connector readiness previously deserialized the full connectors JSON under lock for about 19 seconds; promotion polling used a shorter curl timeout and stacked overlapping `/ready` requests |
| Fix | lightweight DB/Connector probe, bounded per-request timeout, single-flight, `/live` identity check before `/ready`, one overall bounded deadline |
| Post-fix result | Production `/ready` 36ms, Canary `/ready` 38ms, concurrent `/ready` 8x PASS, promote completed in about 27s without hang |

## Auth operational status

| Provider / area | Operational status |
| --- | --- |
| Telegram | Production `login/start` operational; Canary remains `PARTIAL` until a separate Canary bot is provisioned |
| Google | `EXTERNAL BLOCKED` in Production until external Google OAuth configuration/provider is set |
| Email | `EXTERNAL BLOCKED` in Production until a transactional email provider is configured; DEV test auth is not Production acceptance |
| Environment Switcher | PASS: DEV / CANARY / PROD open in separate tabs and origins, cookies/session/CSRF do not carry across, ordinary user does not see DEV/CANARY |

## Trading / execution notes

- Simulation vs real/live is determined by the connected NinjaTrader account,
  not by a separate app-invented product mode.
- NinjaTrader remains the execution authority.
- Application permissions, safety gates, release gates and account capabilities
  decide whether a specific action is allowed.
- Read-only TopstepX never grants execution authority.
- No orders were placed during this acceptance closeout.

## Canonical sources paired with this snapshot

- [../current/NEXT_ARCHITECTURE_PROGRAM_STATUS.md](../current/NEXT_ARCHITECTURE_PROGRAM_STATUS.md)
- [NEXT_ARCHITECTURE_CHANGELOG.md](NEXT_ARCHITECTURE_CHANGELOG.md)
- [../../deploy/canary/README.md](../../deploy/canary/README.md)
- [../../deploy/production/README.md](../../deploy/production/README.md)

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-13T04:59:15Z | GPT-5.5 через Codex по запросу owner | Сохранён компактный canonical operational release snapshot для live 0.10.0-beta.1 / 6b6dc458, чтобы Context Pack ссылался на постоянный repo source, а не на chat history.
-->