# Prompt 11 - Strategy Specification

Turn the attached idea seed into a formal AI Strategy Lab research specification.

Return these sections:

1. `Instrument universe`
2. `Timeframe`
3. `Session window in PT`
4. `Indicators`
5. `Entry rules`
6. `Exit rules`
7. `Risk rules`
8. `Parameters`
9. `Acceptance gates`
10. `Rejection gates`
11. `What to test first`

Rules:

- Historical backtest only.
- Keep the design intraday and force-flat.
- Include stop loss.
- Include take profit or time stop.
- Include max trades per day.
- Require High fill or equivalent conservative fill.
- Require `slippage >= 1`.
- Require `RoundTurnCommission >= 1.90`.
- Do not recommend live trading, paper/demo auto-start, account API, or production deployment.
