# Prompt 06 - Safety Check

Classify each attached AI Strategy Lab action as `allowed`, `blocked`, or `manual_review`.

Return one markdown table with columns:

`Action | Classification | Reason | Required guard`

Rules:

- Live trading automation is blocked.
- Paper/demo auto-start is blocked.
- Historical-only backtests are allowed.
- Locked / accepted / paper-ready / production strategies must be protected.
- AI-generated strategies must stay inside `AI_SANDBOX` / `AI-CELL`.
- Commission must stay enabled with `RoundTurnCommission >= 1.90`.
- Conservative simulation assumptions are required, including High fill or similarly conservative behavior and `slippage >= 1`.
- Do not suggest cleanup or deletion of models.
