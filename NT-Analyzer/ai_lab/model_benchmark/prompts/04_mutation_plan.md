# Prompt 04 - Mutation Plan

Read the attached weak strategy result summary.

Return either:

- `reject` with a short reason, or
- up to 3 mutation proposals.

For each mutation proposal, include:

- `Hypothesis`
- `Parameters to change`
- `Expected effect`
- `Acceptance criteria`
- `Overfit guard`

Rules:

- Change only 1-2 parameters per mutation.
- Avoid broad rewrites or shotgun tuning.
- Keep the plan testable in the next iteration.
- Prefer robust behavior over curve-fit improvements.