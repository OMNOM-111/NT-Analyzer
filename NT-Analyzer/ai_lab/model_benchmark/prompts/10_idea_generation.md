# Prompt 10 - Idea Generation

Generate 5 simple intraday strategy ideas for micro futures research in NT-Analyzer / AI Strategy Lab.

For each idea, return:

- `Name`
- `Instrument universe`
- `Timeframe`
- `Session window in PT`
- `Indicators` with no more than 1-3 indicators
- `Entry rules`
- `Exit rules`
- `Stop loss`
- `Take profit or time stop`
- `Max trades per day`
- `Force flat time`
- `Hypothesis`
- `Why it might work`
- `Why it might fail`
- `Overfit guard`

Rules:

- Historical backtest only.
- Intraday only, no overnight holds.
- Do not suggest live trading.
- Do not suggest paper/demo auto-start.
- Keep ideas simple and testable.
- Avoid parameter-heavy overfit designs.
