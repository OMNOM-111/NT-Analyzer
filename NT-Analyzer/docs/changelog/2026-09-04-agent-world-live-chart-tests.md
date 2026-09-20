# Agent World: real Desktop receipt contract tests

Status: IN DEVELOPMENT; isolated integration verification, not a release or owner visual acceptance.

## Scope

Tests exercise the existing market_data command queue, actual PNG snapshot persistence and existing scoped SF Chat result store through live_charts. There is no headless-render substitution, network request, new queue, duplicate messenger store or production operation. All test writes use disposable runtime/registry roots.

Coverage includes explicit instrument/timeframe, preserved Desktop view, disabled Telegram, scoped command/UUID checks, current capture timestamp and observed bar counts, durable receipt before chat publication, idempotent retry and repair, protected ACK, persistence after command pruning, missing/tampered evidence, genuine PNG format, and concurrent retry.

## Read-only existing NinjaTrader compatibility proof

The current strict LiveBacktestService._verification was run read-only against the owner's existing manual ui_20260905T003301149Z: SampleMACrossOver, MNQ 09-26, 64 trades. Result: passed=true, state=verified, reasons=[]. No origin stamping, job conversion or runtime write occurred; this manual result is not Agent World task evidence.

- result.json SHA256: `509f7e9367a7dd9c10deb1c8148539f13679c8daff5ef26755ca29f1bc3e0f78`.
- bars.json SHA256: `a104cd49ce41681ec7ffb9718197e13271d6a1310b112b6a9171c375342ff558`.
- trades.json SHA256: `3425652c1b35af97c3a36a7567b1833a5a7c690cf59d4468e77b366ff1dbd28f`.

## Verification and ownership

- Combined focused run: `python -m pytest tests/test_agent_world_live_charts.py tests/test_agent_world_live_backtests.py -q` — **113 passed in 13.81 seconds** (56 chart tests plus 57 backtest tests).
- Python compilation of the new test and untracked-inclusive whitespace check of both owned files: **PASS**.
- Regressions identified and fixed by the root implementation owner: unsupported timeframe normalization, malformed PNG acceptance, concurrent capture retries, ignored receipt ACK failure, failed result becoming queued after pruning, and missing command expiration without an open Desktop. Tests now pass without xfail/skip masking.
- The PNG is a genuine small fixture file, not live-market evidence or proof of visual Desktop acceptance. The one separately inspected NT report is a real pre-existing manual result and remains excluded from Agent World ownership.
- Reconciliation's delivered counter counts successful callback attempts, including idempotent retries; tests prove retries do not duplicate chat messages. The read model's 100-task limit is a bounded visible window, not an all-time task count. Existing report aggregates are never reconstructed from sampled trades.
- This subtask edits only the new test and this change record. Root owns app fixes, current/context updates, full regression, commit/PR and actual chat/Desktop/NT acceptance. No version change, merge, release or deployment.
