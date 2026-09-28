# beta.96 product-card parity and status contract

Release title: beta.96 product-card parity and status contract

Release summary: Keep Local beta.95 → beta.96 as the single open product card,
record beta.97–beta.99 as immutable technical iterations inside that card, and
show the owner-defined four-state lifecycle without hiding per-environment gaps.

Source SHA reviewed: `68ba3a95f804800195bb6e8dff556dd843b8eb6e`.

Verification result: PARTIAL. Source ancestry and targeted regression PASS;
full-package Canary parity is not accepted because live beta.99 reports Agent
World and Preview sandbox disabled.

Date: 2026-09-27. Status: **IN DEVELOPMENT / product closeout paused**.
Requester: project owner. Implementation: AI-assisted change.

## Owner contract

The current product card is the Local beta.95 → beta.96 feature package. It
contains SF Social, SF Chat, registration, device trust, Agent World, shared
models, charts for new/Preview users and the Telegram/reporting/server
corrections required to publish this cycle. beta.97, beta.98 and beta.99 remain
their exact historical technical release iterations; none becomes a separate
product milestone and none is renamed.

Every current and future product card and every independent task inside the
open card uses one of four statuses:

- `✓ Done`: only after Development, Local technical verification, explicit
  owner acceptance, Canary and verified Production are all complete;
- `● In progress`: active or otherwise incomplete technical work or rollout;
- `◉ Ready for owner review`: the current technical stage is complete and only
  an owner decision remains; the card must state what to review and the next
  action after approval;
- `○ Planned`: not started, with goal, main requirements and known timing.

Canonical lifecycle: `Planned → In progress → Ready for owner review → In
progress → Done`. The owner-review state may repeat at separate gates. Each card
continues to expose `Development / Local test / Owner / Canary / Production`.

## Technical iteration history inside beta.96

| Iteration | Source SHA | Artifact | Reason and evidence |
| --- | --- | --- | --- |
| beta.96 Local | `56945ac68e94cb7ffa031ef2312dec5a9ad80a54` | Development build `dev-0.10.0-beta.96-56945ac68e94` | accepted Local feature-package basis |
| beta.97 | `4f6bb0b3a0d20712f249afdc9c93538567fd6a8d` | `art_8fec9cdd6ed14dd19cb762291a2a756f` | first server release; SF Chat ↔ Telegram owner path, restart-persistent topics, stable-key dedupe and Deputy reporting route |
| beta.98 | `0b9233d7c8983adc0a3a6c37350a3974770cb738` | `art_b05720a1f2d44672805b45b513f0203e` | reload-loop correction; Canary exposed the separate entitlement-storage blocker |
| beta.99 | `68ba3a95f804800195bb6e8dff556dd843b8eb6e` | `art_3ae473a96bb24d439fd5cb6d3a1d1096` | authoritative server entitlement storage; final-main CI `36365092457` PASS; same signed artifact is live on Canary and Production |

Owner approvals remain attached to their actual gates: Local beta.96 was
accepted as the release basis on 2026-09-26; PR #294 and exact beta.97 Production
artifact were separately approved on 2026-09-27; PR #299 and exact beta.99
Production artifact were separately approved later on 2026-09-27. These facts do
not create product-card `Done` while an end-to-end stage remains incomplete.

## Package parity evidence

- `56945ac68e94cb7ffa031ef2312dec5a9ad80a54` is an ancestor of final beta.99
  source `68ba3a95f804800195bb6e8dff556dd843b8eb6e`;
- the application delta after beta.96 is confined to version metadata and the
  Telegram/reporting, reload-loop and subscription-routing corrections plus
  their tests/docs; core beta.96 feature modules were not removed;
- 327 targeted tests for SF Social, SF Chat, registration, device trust, Agent
  World, shared models, Preview/new-user parity, trial access and Aurora
  contracts PASS on the final SHA;
- live Canary beta.99 identity/readiness, separate non-owner Professional
  workspace/entitlement/session, cold start, restart persistence, SF Social,
  SF Chat and runtime-bars API checks PASS;
- live Canary reports `agent_world.enabled=false`, status `IN DEVELOPMENT`, and
  `preview_sandbox.enabled=false`. Therefore full beta.96 feature parity is
  PARTIAL and the product card remains `● In progress`;
- beta.99 is already live in Production under the earlier artifact-specific
  approval. Its identity/readiness and owner/non-owner cold-start smoke PASS,
  but final product closeout is paused and is not recorded as `Done`.

Production periodic schedulers remain OFF and Local `StratForge Vitek` remains
ON. Ordinary-user Telegram onboarding/isolation issue #296 is not a completed
beta.96 capability; it remains a separate next task after this product card.

## Next gate

Resolve or explicitly re-scope the server-disabled Agent World and Preview
sandbox gaps, repeat full-package Canary acceptance, and only then enter
`Ready for owner review` with an exact owner checklist and next action. No new
application artifact is created by this documentation correction.
