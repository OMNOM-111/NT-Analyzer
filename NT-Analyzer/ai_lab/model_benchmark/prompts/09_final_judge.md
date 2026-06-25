# Prompt 09 - Final Judge

You are the final AI Strategy Lab judge.

Use the attached benchmark cases to make conservative decisions.

Return:

1. A markdown table with columns `Case | Decision | Reason | Required next step`.
2. `Best current model-lab action`: one short paragraph.
3. `Safety gate`: one short paragraph.

Decision vocabulary is exactly: `reject`, `mutate`, `candidate`, `promote`.

Rules:

- Strategy B from the sample backtest metrics is the only plausible current candidate if you agree with the evidence.
- Strategy A should not pass if OOS is negative.
- Strategy C should not pass on headline profit alone because same-bar ambiguity and low sample size matter.
- The overfit case should be rejected unless you can justify otherwise from robust OOS evidence.
- Never promote to production from these inputs.
- Never recommend live trading, paper/demo auto-start, account API, or automatic deployment.
- Require High fill or equivalent conservative fill, `slippage >= 1`, and `RoundTurnCommission >= 1.90`.
