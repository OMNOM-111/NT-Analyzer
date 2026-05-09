# NTAMicroVwapRiskExplorer — research fork

This is a **research fork** of `NTAMicroVwapRiskPilot`. Trading logic is identical;
only the class name (and therefore the NinjaScript whitelist entry, parameter
defaults table and locked-profile mapping) differ.

## Purpose

`NTAMicroVwapRiskPilot` is locked to its accepted MNQ paper profile
(`b1_shortonly_mnq_5m_high_slip1_paper_v2`) — backend force-applies its locked
parameters on every job (`app/jobqueue.py:_apply_locked_strategy_parameters`).
That makes the original class unusable for honest research on other instruments.

`NTAMicroVwapRiskExplorer` exists so we can vary parameters and instruments
**without touching the locked MNQ pilot**. MNQ is intentionally excluded from
Explorer searches.

## Rules

- All Explorer backtests use `role="research"`, `order_fill_resolution="High"`,
  `slippage_ticks>=1`, `RoundTurnCommission>=1.90`, `commission_template="None"`.
- MNQ is excluded from Explorer ranking and profile creation.
- Current backend/bridge path fixes `session_template="CME US Index Futures RTH"`. Only
  index micros (MES/MYM/M2K) get a TradingHours template that actually matches
  the market. Non-index micros (MGC/MCL/MNG/MBT/MET/M6A/M6B/M6E/MHG/SIL...)
  run with the wrong session and therefore CANNOT be promoted to `paper_ready`
  — at most `research_candidate` / `exploratory_only`.

See `data/research/vwap_explorer_*` for produced reports.
