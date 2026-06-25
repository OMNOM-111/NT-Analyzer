# Prompt 02 - Code Review

Review the attached NinjaTrader strategy for NT8 compatibility, correctness, and safety.

Return these sections:

1. `Critical findings`
2. `Compile risks`
3. `Logic / risk issues`
4. `Minimal fix plan`
5. `Corrected snippet`

Rules:

- Focus on actual NT8 issues, not generic style comments.
- Call out old NT7 namespace / API usage.
- Call out missing NinjaScript properties and missing risk controls.
- Call out logic mismatches such as long entries in a short setup.
- Do not invent fake NinjaTrader APIs.
- Keep the corrected snippet minimal and practical.