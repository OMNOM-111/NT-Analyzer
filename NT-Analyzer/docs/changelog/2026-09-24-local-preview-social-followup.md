# Local Preview exit, public profiles and model sharing visibility

Status: IN DEVELOPMENT — focused implementation checks PASS; manual acceptance pending. Live onboarding charts: EXTERNAL BLOCKED by source readiness.
Source baseline: `023fd4c40232b98fcef8f1cbd900fcabccc314cf`; branch `codex/shared-model-local-completion`; draft [PR #291](https://github.com/OMNOM-111/NT-Analyzer/pull/291).
Scope: Local only. No Server, Canary, Production, permission-grant or provider-credential changes.

## Corrections

- Registration is already a wall entry: its presence suppresses the misleading empty-wall invitation; empty saved-post lists keep their own message.
- Public Preview projection retains the actual public profile name and bounded image bytes. The existing authenticated profile-avatar endpoint serves the image, without account IDs, filesystem paths, private profiles or credentials crossing the boundary. Chosen profile names are preserved; generated placeholders refresh from account data.
- Owner Models table includes explicit shared/private state sourced from the same model connection catalog as the card toggle. Unavailable catalog state is not misrepresented as private.
- Preview Exit closes mutations and erases disposable data before responding, then shuts down only after flushing the response. A cached tab whose child has already stopped returns through the existing loopback owner-return route. The original active owner session and cookie lifetime are preserved. Only the matching Preview id may be cleaned up; a stale tab cannot stop a newer run. Browser navigation replaces the dead Preview history entry and returns directly to the owner interface.

## Source blocker, verified on Local

The existing `shared_trial` resolver and single TopStep hub/consumer fan-out remain intact. Both runtime TopStep source authorization flags are false. Databento historical is `configured=false`, `credential_state=placeholder`; the live adapters report `MOCK_SIMULATION` / `REALTIME_PRODUCTION=false`. Yahoo is `DELAYED_OR_UNVERIFIED`, explicitly forbidden as live. There is no configured alternative authorized live source for unrelated trial accounts in this checkout/runtime.

The latest product requirement is immediate real live charts for normal/trial onboarding, with no synthetic replacement. This requirement is **not accepted as complete**. The prior DEMO fallback is no longer an accepted product result. Automatic safety review rejected removing that fallback before a usable live source is available, because it would leave trial charts empty. The rejected command made no market-code changes. Source selection requires the owner's existing authorized provider access; no policy bit, credential or subscription is invented.

References: [source contract](../architecture/MARKET_DATA_USER_ENTITLEMENT_STRATEGY.md), [live adapter readiness](../architecture/MARKET_DATA_LIVE_SOURCES_MILESTONE.md). The older Preview parity acceptance describes the prior demo requirement and does not certify this new live-source requirement.

## Verification

209 tests passed across complete Preview, Social, model-inline and Aurora contract modules, including new regressions for real avatars, names, registration-only walls, session preservation, stale Preview ids and response/shutdown ordering. 105 additional chat/shared/market boundary tests PASS. Real browser acceptance is recorded at closeout. Previous full-regression counts remain bound to the previous code.
