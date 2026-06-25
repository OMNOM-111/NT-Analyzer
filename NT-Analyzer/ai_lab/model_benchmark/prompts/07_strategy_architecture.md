# Prompt 07 - Strategy Architecture

Design a safe local-model architecture for NT-Analyzer / AI Strategy Lab.

Return these sections:

1. `Role map`
2. `Read-only benchmark and audit artifacts`
3. `Historical backtest workflow`
4. `Safety gates`
5. `Failure handling`

Rules:

- NinjaTrader 8 remains the source of truth for compile and historical backtest results.
- LLMs may draft ideas, code, reviews, fixes, analysis, mutation plans, safety checks, and final judge decisions.
- Do not allow live trading, paper/demo auto-start, account API, or automatic production deployment.
- Keep AI-generated strategies inside `AI_SANDBOX` / `AI-CELL`.
- Protect locked / accepted / paper-ready strategies.
- Require human approval before promote-like decisions.
- Mention how prompts, raw responses, scores, and model-role config should be recorded.
- Keep the answer concise and operational.
