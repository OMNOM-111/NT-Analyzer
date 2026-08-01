# Repository hygiene

История поправки: 2026-08-01T23:47:37Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: Stage 10 Repository Hygiene Closeout.

## Stage 10 closeout record

Stage 10 выполняет только repository hygiene closeout. Не запускалась Phase 1-10 новой архитектуры, не менялась Production-конфигурация, не выполнялся deployment и не менялось поведение приложения за пределами fail-safe теста пустого runtime registry.

## Runtime AI Lab registry

Классификация: runtime data, не fixture, не seed и не canonical config для обычной истории Git.

Точные ignored-пути:

- `NT-Analyzer/data/ai_lab/registry/agent_usage/`
- `NT-Analyzer/data/ai_lab/registry/chief_reports/`
- `NT-Analyzer/data/ai_lab/registry/chief_agent.json`
- `NT-Analyzer/data/ai_lab/registry/news_agent.json`
- `NT-Analyzer/data/ai_lab/registry/orchestrator_conversation.jsonl`
- `NT-Analyzer/data/ai_lab/registry/orchestrator_conversations.json`

Tracked runtime files under these paths are removed from the Git index with `git rm --cached` only. Local files must remain on disk and must be verified after cleanup.

Fail-safe requirement: app code must tolerate missing runtime registry files/directories and recreate them on write. Covered by `tests/test_ai_agents.py::test_ai_lab_runtime_registry_recreates_missing_files`.

## Governance generated output

Date-only dirty output in these generated/mirrored docs must be restored to HEAD unless the same commit includes canonical source-of-truth and amendment/changelog evidence:

- `NT-Analyzer/data/governance-rendered/LAWS.md`
- `NT-Analyzer/data/governance-rendered/LOCAL_AI_LAWS.md`
- `NT-Analyzer/data/governance-rendered/SYNC_MAP.md`
- `NT-Analyzer/docs/governance/LAWS.md`
- `NT-Analyzer/docs/governance/LOCAL_AI_LAWS.md`
- `NT-Analyzer/docs/governance/SYNC_MAP.md`

Generated governance output can be committed only with canonical source plus changelog/amendment evidence. Otherwise it is treated as restart/date noise.

## Rollback bundle

Path: `NT-Analyzer/dev10-reconstructed-rollback.bundle`.

- SHA256: `75511284F64B9C59C54B3078B1C8E5D641B526D1A95EC714151CEBA76457F283`
- Size: `11788600` bytes.
- Verification: `git bundle verify` reports a valid complete history, sha1 hash algorithm.
- Refs: 32 refs; HEAD `ca4dcf0cd5761dca5a9c0b775f7bfd029e28c1f6`, `refs/heads/antigravity/dev10-reconstructed`.
- Purpose: local rollback artifact for reconstructed dev10 state.

The bundle is ignored by exact path and preserved locally. Do not commit it. Recommended external storage: private GitHub Release or private artifact storage only after isolated clone/unbundle secret scan.

## Documentation archive

Original path: `NT-Analyzer/docs.zip`.

Moved artifact path: `C:\Users\dimon\Documents\StratForge-Artifacts\documentation\docs-2026-08-01-0231575D.zip`.

- SHA256: `0231575D1E8573AA19863FD138EEE20724148854563DEC6E115BCA2F3417ED83`
- Size: `277516` bytes.
- Comparison with current `NT-Analyzer/docs/`: 74 file entries checked, 71 exact matches, 0 missing files, 3 differing files.
- Differing files: `docs/governance/LAWS.md`, `docs/governance/LOCAL_AI_LAWS.md`, `docs/governance/SYNC_MAP.md`.

The archive is ignored by exact source path and preserved outside the working tree. Do not delete without owner approval.

## Architecture audit copy

Source: `C:\Users\dimon\Desktop\ARCHITECTURE_PLAN_TASK_1\STRATFORGE_NEXT_ARCHITECTURE_AUDIT_AND_IMPLEMENTATION_PLAN.md`.

Repository copy: `NT-Analyzer/docs/current/STRATFORGE_NEXT_ARCHITECTURE_AUDIT_AND_IMPLEMENTATION_PLAN_2026-08-01.md`.

Classification: Phase 0 audit and implementation plan. Local paths remain only as audit evidence. Secret/path check found documentation references to secrets/tokens but no high-confidence plaintext credentials in the copied report.

## Closeout boundaries

- No Production secrets/server/DB access.
- No deployment.
- No release.
- No merge.
- No Phase 1-10 architecture implementation.
- No deletion of local runtime data or rollback artifacts.
