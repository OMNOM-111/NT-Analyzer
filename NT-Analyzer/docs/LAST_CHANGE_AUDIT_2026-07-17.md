# Last-change audit — 2026-07-17

Branch: `codex/stratforge-release-20260716`
Audit status: **repository implementation reconciled; automated gates pass; production acceptance blocked**

## Attribution and scope

Git records every recent commit under `dimon <dimon@users.noreply.github.com>`.
It does not record which Codex/Cursor/other task produced an uncommitted line, so
agent-level authorship cannot be reconstructed reliably and is not invented here.
Functional ownership can be reconstructed from commit subjects, run-state notes,
tests and code boundaries:

| Contour | What changed | Why |
|---|---|---|
| StratForge release A–E | tenant/auth/product gates, durable worker, Aurora routes, Practice and Micro Live scaffolds | make the product contour testable without enabling unsafe real-money paths |
| AI staff / TTS | preserved personas, Azure/OpenAI speech resolution, CSP `blob:` media, dialogue docs | keep one consistent employee identity and make voice preview work safely |
| Startup safety | NinjaTrader default-off in UI, PowerShell and Python bootstrap | avoid surprise login dialogs and post-reboot account lockouts |
| Market-data safety | offline truthfulness, provider/freshness labels, cache sanitizing, no fake LIVE | frozen/history data must never look executable/live |
| Bridge IPC | bounded queue, authenticated localhost transport, heartbeat/reconnect and diagnostics | move callback ticks without file I/O or blocking NinjaTrader callbacks |
| Browser delivery | authorized same-origin `/ws/market-data`, HTTP fallback and coalescing | support many panels without one upstream subscription per panel |
| BYOMD | entitlement schema/prototypes, private/workspace cache scopes, provider plans | prepare user-owned feeds without claiming redistribution rights or production readiness |

## Defects found and closed in this audit

1. IPC benchmark used fixed port `18766` and failed on reserved Windows ports.
   It now asks the OS for an ephemeral port.
2. AI Lab tests/documentation said NinjaTrader autostart was disabled, but
   `bootstrap.py` still defaulted to start it and lacked the env gate. The Python
   implementation now requires both an explicit request and
   `NTA_ALLOW_AUTOSTART_NINJATRADER=1`.
3. TopstepX prototype used non-official SignalR target names, numeric contract IDs
   and the wrong callback shape. It now follows ProjectX string `CON.F...` IDs and
   `SubscribeContractQuotes` / `SubscribeContractTrades`; it remains explicitly
   opt-in and unverified with real credentials.
4. A second localhost browser WebSocket server duplicated the authorized
   same-origin route and accepted weak `session:*` placeholders. Startup and
   broadcast now use only `/ws/market-data` on the main authenticated server.
5. L2 diagnostic cache keys did not include tenant scope while BYOMD docs promised
   isolation. Cache keys now support `global`, `workspace` and strict `private`
   scopes, with collision/isolation tests.
6. Malformed entitlement expiry values failed open. They now fail closed.
7. BYOMD documentation contained stale price/protocol claims and an absolute
   `file:///C:/Users/...` link. It now uses repository-relative links, official
   ProjectX/Topstep references, and marks vendor/legal acceptance honestly.
8. A test-generated governance overview temporarily erased amendment history.
   The artifact was removed and the canonical history restored.
9. Trailing whitespace and a spurious EOF block made `git diff --check` fail.
   The changed files are clean now.

## Verification evidence

| Gate | Result |
|---|---|
| `python -m pytest -q` | **682 passed** in 170.53 s |
| `python -m tests` | **13/13 suites passed** |
| Focused market-data / entitlement / IPC | **35 passed** |
| AI Lab bootstrap | **93/93 passed** |
| Python changed-file compile | **PASS** |
| JavaScript changed-file `node --check` | **PASS** |
| Changed JSON parse | **PASS** |
| `dotnet build bridge/NTAnalyzerBridge.csproj -c Release --no-restore` | **PASS**, 0 warnings, 0 errors |
| `git diff --check` | **PASS** |
| Secret-pattern review of added lines | placeholders/mocks only; no live credential found |
| Bridge DLL install | **PASS**, build/install SHA-256 `24F7DC...C514F`; backup retained |

## Not production-accepted

- No in-app browser was launched under the workspace stability rule. Manual
  Desktop/mobile/two-profile/Telegram visual acceptance is still **BLOCKED**.
- Live NinjaTrader callback → IPC → same-origin WS, controlled NT kill/restore and
  Strategy Analyzer comparison still need an owner-controlled run.
- TopstepX has no sandbox according to its current official help; no credentialed
  TopstepX/Databento/Rithmic/CQG production acceptance was performed.
- PostgreSQL/Redis production services and the 100-user load report are not present.
- Payment/broker real-money adapters remain intentionally unavailable.

Automated PASS therefore means the repository is coherent enough to commit and
continue problem-by-problem; it does not mean `ACCEPTANCE PASSED`,
`100-USER LOAD PASSED`, or `PRODUCTION FAILOVER COMPLETE`.
