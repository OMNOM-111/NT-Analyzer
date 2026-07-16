# Codex premature-exit investigation — 2026-07-16

Timezone: America/Los_Angeles (PT)

## Conclusion

The two latest interrupted runs did not end because of a Git branch switch, a project cleanup script, a context limit or disk/memory exhaustion.

1. The 01:15 interruption is most likely a Codex Desktop race/failure during concurrent plugin installation and MCP-server refresh. Windows recorded native exception `0xc06d007f` for `ChatGPT.exe`; Codex logs show three simultaneous `plugin/install` requests, repeated skills-cache invalidation and MCP refreshes immediately before the exception.
2. The 02:29 interruption was caused by a planned Windows Update restart. Immediately after boot Windows upgraded the Codex app package from `26.707.9981.0` to `26.707.12708.0`; the newly started app then had one additional native `0xc06d007f` startup failure.

The exact native function that threw `0xc06d007f` cannot be proven from the available evidence: WER reports the faulting module as `unknown`, and no WinDbg/`dumpchk` analyzer or matching private symbols are installed. Browser involvement is not proven for the 01:15 crash. The refresh configuration included the in-app Browser/computer-use runtime, but the direct event preceding the crash was plugin installation/MCP refresh, not a recorded page navigation.

## Evidence timeline

### Interruption 1 — plugin installation/MCP refresh

- 2026-07-16 01:15:12: Codex log warns while loading the temporary plugin catalog.
- 01:15:13: three separate `plugin/install` RPC requests begin.
- 01:15:13–01:15:16: multiple active sessions receive `RefreshMcpServers`; skills cache is repeatedly cleared. The runtime config includes `node_repl`, Browser and computer-use native pipes.
- 01:15:13: connector directory request starts; its response is about 3.45 MB.
- 01:15:13: document, PDF and spreadsheet plugin cache directories are created.
- 01:15:18 and 01:15:23: Windows Application Error 1000 records `ChatGPT.exe` PID 28888, Codex package `26.707.9981.0`, exception `0xc06d007f`, faulting module `unknown`.
- 01:15:22 and 01:15:28: WER writes `ChatGPT.exe(6).28888.dmp` and `ChatGPT.exe(7).28888.dmp`.
- 01:15:28–01:15:29: presentation/template plugin cache writes complete, consistent with the installation continuing around the desktop-process failure.

Assessment: **most likely Codex Desktop plugin-install/MCP-refresh race or native app defect**. The dump proves the native failure; correlation establishes the most likely trigger, but symbols would be required to name the exact function.

### Interruption 2 — planned OS restart, app upgrade and startup crash

- 02:29:11: System/User32 event 1074 says `MoUsoCoreWorker.exe` initiated a planned restart for operating-system update installation.
- 02:29:17: EventLog 6006 reports the event-log service stopped.
- 02:29:24: Kernel-General 13 records OS shutdown time.
- 02:29:46: Kernel-General 12 records the next OS boot.
- 02:30:05–02:30:37: AppX deployment events register Codex `26.707.12708.0`, explicitly update from `26.707.9981.0`, and remove the old package directory.
- 02:31:27: Application Error 1000 records new `ChatGPT.exe` PID 24688, exception `0xc06d007f`, faulting module `unknown`.
- 02:31:30: WER writes `ChatGPT.exe.24688.dmp`.

Assessment: **confirmed planned Windows Update restart** ended the prior process tree. A separate Codex startup defect occurred after the package upgrade.

## Negative findings

- No Resource-Exhaustion-Detector, Kernel-Power 41, unexpected-shutdown 6008, disk or NTFS failure was recorded for the relevant period.
- At audit time: about 44.24 GB of 63.9 GB RAM was free and about 385.9 GB of C: was free.
- Project search found no code that targets `ChatGPT.exe`, Codex, Extension Host or a parent terminal. The only `taskkill` call is `tunnel_manager._stop_pid`, which targets the stored Cloudflared child PID.
- PowerShell history contains no `taskkill` or `Stop-Process` command targeting ChatGPT/Codex.
- Git reflog shows the release-branch switch at 04:18, hours after both interruption windows.
- The product is the standalone Codex Desktop package, so a VS Code Extension Host was not part of these failures.
- Earlier Windows records include `AppHangTransient` for ChatGPT, including 2026-07-13. This supports the workspace warning about browser-related hangs, but it does not change the specific 01:15/02:29 findings above.

## Recovery controls adopted

- Persistent checkpoint: `docs/CODEX_RUN_STATE_2026-07-16.md`.
- Atomic commit after each independent stage.
- Clean commit before Browser/computer-use work; immediate checkpoint after it.
- No plugin installation or plugin refresh will be intentionally performed during Browser QA.
- Full original dirty tree remains reachable from `codex/stratforge-pre-separation-safety`.
