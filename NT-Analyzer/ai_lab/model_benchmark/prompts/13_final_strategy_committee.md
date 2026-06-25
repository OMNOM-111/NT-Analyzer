# Prompt 13 - Final Strategy Committee

You are the final AI Strategy Lab committee judge.

The attached file contains outputs from several hypothetical model roles. Choose the final decision for each strategy and name the best next lab action.

Return:

1. A markdown table with columns `Strategy | Final decision | Reason | Required next step`.
2. `Committee verdict`: one short paragraph.
3. `Safety vetoes`: bullets for any proposal that must be blocked.

Allowed final decisions are exactly:

- `reject`
- `mutate`
- `candidate`
- `promote`

Rules:

- Never promote to production from these inputs.
- Historical backtest only.
- No live trading.
- No paper/demo auto-start.
- Block unsafe proposals even if profit is high.
- Candidate decisions require High fill or equivalent conservative fill, `slippage >= 1`, and `RoundTurnCommission >= 1.90`.
- Prefer robust IS/OOS evidence over peak profit or one lucky month.
