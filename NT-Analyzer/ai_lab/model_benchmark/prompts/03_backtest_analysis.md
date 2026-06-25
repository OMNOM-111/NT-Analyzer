# Prompt 03 - Backtest Analysis

You are acting as the AI Strategy Lab judge.

Analyze the attached metrics for strategies `A`, `B`, and `C`.

Return:

1. A markdown table with columns `Strategy | Decision | Why` where decision is one of `reject`, `mutate`, or `candidate`.
2. A short paragraph naming the best current option.
3. A short paragraph with the next validation step.

Rules:

- Prefer adjusted and commission-aware metrics.
- Reject OOS-negative strategies even if headline profit is high.
- Penalize low sample size.
- Penalize high same-bar ambiguity.
- Prefer robust IS/OOS balance and acceptable drawdown over the highest raw profit.
- Do not recommend live trading.