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
