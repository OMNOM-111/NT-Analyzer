# UI routes and rollback

## Active routes

| URL | Result |
|---|---|
| `/`, `/ui/`, `/ui/index.html` | Aurora Overview (primary) |
| `/ui/backtesting.html` ... `/ui/documents.html` | Aurora operational pages |
| `/ui/news.html` | официальный экономический календарь, live-источники, фильтры, критические предупреждения и нижняя лента |
| `/ui/topstep.html` | read-only TopStep integration status |
| `/ui/assets/*` | Aurora assets |
| `/ui/legacy/`, `/ui/legacy/<file>` | HTTP 410; classic UI isolated from current runtime |
| `/ui/ai-strategy.html` | redirect to Aurora AI Lab |
| `/ui/ops.html` | redirect to Aurora Trading |
| `/ui/docs.html` | redirect to Aurora Documents |
| `/ui/aurora/*` | canonical redirect to `/ui/*` |

`start.ps1` opens `/ui/`. `start-ai-lab.ps1` opens `/ui/ai-lab.html`.
Restarting the application therefore opens Aurora by default.
Classic page tabs and deep links are absent from the current server. Historical
reports are inspected through the separate Legacy Viewer described in
`LEGACY_VIEWER.md`.

## Legacy boundary

- Aurora has no navigation or switch to the classic UI.
- Retired Mini App, remote-access and tunnel routes return HTTP 410.
- `Start StratForge Legacy.cmd` starts a separate localhost-only viewer on port
  8876 by default; it does not share current cookies or writable data.

## Backup

Authoritative pre-completion backup:

`C:\Users\dimon\Documents\NT-Analyzer-UI-backups\completion_20260628_165804`

It contains a 2,954-file project snapshot including mutable `data`, git status,
binary diff, `repo.bundle`, SHA-256 manifest, AI-run state and `RESTORE.txt`.

Post-completion verified snapshot:

`C:\Users\dimon\Documents\NT-Analyzer-UI-backups\final_20260628_174947`

It contains 2,970 files (190,141,393 bytes), a matching 2,970-row SHA-256
manifest, final ledger/cell data, binary diff and repository bundle.

Archived prototype/audit material removed from the workspace:

`C:\Users\dimon\Documents\NT-Analyzer-UI-backups\final_cleanup_20260628_183443`

Its `prototype_archive` contains the former `test_design_ui`,
`ui_audit_screens`, audit report and obsolete Claude task document. The
46-file SHA-256 manifest was generated and verified before deletion.

Final Git-visible release snapshot:

`C:\Users\dimon\Documents\NT-Analyzer-UI-backups\release_final_20260628_183903`

It contains 590 current files (7,706,535 bytes), a verified SHA-256 manifest,
the 20 deleted tracked paths, binary working-tree diff and a full Git bundle.

## Restore

For a full restore, follow the backup's `RESTORE.md`. The essential commands are:

```powershell
$bk = 'C:\Users\dimon\Documents\NT-Analyzer-UI-backups\completion_20260628_165804\project_snapshot'
$dst = 'C:\Users\dimon\Documents\Анализатор стратегий NinjaTrader\NT-Analyzer'
robocopy $bk $dst /E
```

Then restart the backend. Do not use `git reset --hard`: the worktree contains
independent uncommitted research and strategy changes.
