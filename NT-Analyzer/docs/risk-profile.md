# Risk Profile v0.1

Risk Profile is an account-context block for realistic strategy development.
In this build it is **informational only**: it is saved into `job.json` and
echoed back in `result.context.risk_profile`, and the UI uses it to display
starting capital and per-instrument availability by margin. It does **not**
block orders, change strategy execution, or alter the validated NinjaTrader
Strategy Analyzer backtest path. The bridge passes the block through
unchanged.

## Manual UI inputs

The Account / Risk Profile panel collects only two fields from the user:

- `starting_capital` — starting USD account value.
- `intraday_only` — toggle. When true, only intraday (broker day-trading)
  margin is considered. When false, the overnight / initial exchange margin
  is considered.

Per-contract margin numbers are no longer entered by hand; they are looked
up from the local **Margin Catalog** (see below).

## Margin Catalog

`NT-Analyzer/data/catalog/margins.json` is a local broker-margin reference,
keyed by futures **root symbol** (`MES`, `MNQ`, `ES`, …). The backend reads
the file in `read_margins_catalog()` and exposes it under
`/api/catalog → margin_catalog`.

Schema (v0.1):

```json
{
  "schema_version": "0.1",
  "broker": "NinjaTrader",
  "source": "manual_seed",
  "source_url": "https://ninjatrader.com/pricing/margins-position-management/",
  "fetched_at_utc": "2026-04-29T00:00:00Z",
  "notes": [
    "Intraday margins can change without notice.",
    "News events may temporarily increase intraday margins."
  ],
  "symbols": {
    "MES": {
      "display_name": "Micro E-mini S&P 500",
      "exchange": "CME",
      "intraday_margin": 50.0,
      "initial_margin": null,
      "maintenance_margin": null
    }
  }
}
```

If `margins.json` is missing the backend returns an empty catalog block plus
a warning, and the UI continues to load — instruments are simply marked
`unknown`.

### Source policy

- **Intraday / day-trading margin** is broker-defined. Values come from
  NinjaTrader’s public per-symbol margin page
  (`https://ninjatrader.com/pricing/margins/`). Treat the values as
  **a reference, not a contract**: brokers may change intraday margin
  without notice and may temporarily raise it around news events.
- **Initial margin** (the `initial_margin` field) is the broker-published
  overnight requirement and is also pulled from the same page.
- **Maintenance margin** is exchange-driven and is **not** published per
  symbol on the broker margins page; the field stays `null`.

### Auto-refresh

The catalog is refreshed automatically and on demand. Both paths share
the same fetch + parse + atomic-write code in `app/marginrefresh.py`.

- **Daily auto-refresh.** On the first `/api/catalog` request after
  `margins.json` is older than ~24 hours, the backend dispatches a
  background daemon thread that fetches the broker page, parses the
  symbol table, and rewrites `margins.json` atomically with
  `source = "auto_refresh"`, a fresh `fetched_at_utc`, and `trigger`
  set to `"auto"`. The HTTP request that triggered the check is **not**
  blocked.
- **Manual “Обновить маржи” button** in the Account / Risk Profile
  panel posts to `POST /api/margins/refresh`. The server runs the same
  refresh code synchronously and returns
  `{ ok, fetched_at_utc, symbols_count, source_url, error? }`. On
  success the UI reloads `/api/catalog` and recomputes the risk
  profile.
- **Failure handling.** If the network request, HTML parse, or atomic
  write fails for any reason, the existing `margins.json` snapshot is
  left untouched. The error is recorded in
  `marginrefresh.last_status()` and surfaced both as a `warnings[]`
  entry on `/api/catalog` and as a hint next to the refresh button. The
  UI keeps working off the last successful snapshot.

This is still a pure information layer — the refresher must never
modify strategy execution, the bridge, Account binding, or order flow.

The previous build shipped a `manual_seed` `margins.json`. After this
change `source` becomes `auto_refresh` once the first refresh succeeds.

## UI behavior

For each instrument in the basket the UI:

1. Extracts the root symbol — `"MES 06-26"` → `"MES"`.
2. Looks the root up in `margin_catalog.symbols`.
3. Picks `intraday_margin` when `intraday_only=true`, otherwise
   `initial_margin`.
4. Computes:
   - `status = "unknown"` if the chosen margin is `null` or absent.
   - `status = "allowed"` if `starting_capital >= margin`.
   - `status = "blocked"` if `starting_capital < margin`.
   - `max_contracts_by_capital = floor(starting_capital / margin)` when
     `margin > 0`.

The panel renders a compact summary (`Можно: N / Недоступно: N / Нет
данных: N`) followed by the per-instrument breakdown.

## Wire format saved into `job.json`

```json
"risk_profile": {
  "schema_version": "0.1",
  "mode": "informational",
  "currency": "USD",
  "starting_capital": 2000.0,
  "intraday_only": true,
  "margin_source": {
    "broker": "NinjaTrader",
    "source": "manual_seed",
    "fetched_at_utc": "2026-04-29T00:00:00Z"
  },
  "instrument_margins": {
    "MES 06-26": {
      "root": "MES",
      "margin_type": "intraday",
      "margin_per_contract": 50.0,
      "max_contracts_by_capital": 40,
      "status": "allowed"
    }
  },
  "status": "informational_only",
  "status_text": "Risk Profile сохранён в запуске; стратегия пока не ограничивается."
}
```

Older jobs created before this schema may carry the legacy
`margin_per_contract.{intraday,overnight,active}` block; the UI summary in
the result panel still renders those for back-compatibility.

## Strategy / bridge contract

- `StrategyAnalyzerRunner` execution is unchanged — Account binding,
  ordering, entries/exits and NinjaTrader-side metrics are not touched.
- The bridge already echoes `risk_profile` into `result.context` via
  `ResultBuilder.Build()` (`riskProfile?.DeepClone()`); no bridge change is
  required for this iteration.
- A future step will introduce a shared RiskManager contract that
  strategies can opt in to. Until then the profile is purely informational.
