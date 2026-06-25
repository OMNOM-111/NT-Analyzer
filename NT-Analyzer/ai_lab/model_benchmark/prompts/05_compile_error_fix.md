# Prompt 05 - Compile Error Fixing

You are given a bad NinjaTrader strategy and a compile-error list.

Return these sections:

1. `Root causes`
2. `Fix plan`
3. `Corrected fragment`

Rules:

- Explain why the compile failures happen.
- Convert NT7-style assumptions to NT8-compatible fixes when needed.
- Avoid fake APIs.
- Keep the corrected fragment focused on the actual errors.
- Preserve the strategy's general intent, but fix obvious risk and logic problems when they are tightly coupled to the compile issues.