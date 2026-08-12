# docs/archive

Historical, superseded and dated point-in-time material. Documents here are kept
for provenance only and are **not** current architecture, runbooks or policy.
Do not treat anything under `docs/archive/` as authoritative for the running
system — consult `docs/current/`, `docs/architecture/` and `docs/operations/`
instead.

- `audits/` — dated point-in-time audits.

The set of files destined for this directory is listed in the migration map,
`docs/DOCS_STRUCTURE.md`. Each file is relocated with `git mv` and every inbound
reference is rewritten in the same step, verified by the markdown link audit, so
no move lands with a broken link.

## Relocated repo-root historical snapshots (2026-08-10)

Moved here from the repository root because they are dated snapshots, no longer a
current source of truth. History preserved via `git mv`; inbound links rewritten.
Relocation by `GitHub Copilot (Claude Opus 4.8) через VS Code по запросу owner`.

- `STRATFORGE_ГЕНЕРАЛЬНЫЙ_ПЛАН.md` — dated developer task/audit (15 July 2026).
  Superseded on product-boundary matters (Micro Live removed 2026-07-18); the
  current program status lives in `docs/current/`.
- `ПОДРОБНАЯ_ИНСТРУКЦИЯ.txt` — early NinjaTrader-centric detailed instruction
  (2026-05-08). Current entry docs are `README.md` and `NT-Analyzer/README.md`.
