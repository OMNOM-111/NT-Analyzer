# Local Preview exit, public profiles and model sharing visibility

Status: IN DEVELOPMENT — focused implementation checks PASS; manual acceptance pending. Canonical common TopStep mirror implemented; current manual acceptance pending.
Source baseline: `023fd4c40232b98fcef8f1cbd900fcabccc314cf`; branch `codex/shared-model-local-completion`; draft [PR #291](https://github.com/OMNOM-111/NT-Analyzer/pull/291).
Scope: Local only. No Server, Canary, Production, permission-grant or provider-credential changes.

## Corrections

- Registration is already a wall entry: its presence suppresses the misleading empty-wall invitation; empty saved-post lists keep their own message.
- Public Preview projection retains the actual public profile name and bounded image bytes. The existing authenticated profile-avatar endpoint serves the image, without account IDs, filesystem paths, private profiles or credentials crossing the boundary. Chosen profile names are preserved; generated placeholders refresh from account data.
- Owner Models table includes explicit shared/private state sourced from the same model connection catalog as the card toggle. Unavailable catalog state is not misrepresented as private.
- Preview Exit closes mutations and erases disposable data before responding, then shuts down only after flushing the response. A cached tab whose child has already stopped returns through the existing loopback owner-return route. The original active owner session and cookie lifetime are preserved. Only the matching Preview id may be cleaned up; a stale tab cannot stop a newer run. Browser navigation replaces the dead Preview history entry and returns directly to the owner interface.

## Canonical live mirror contract

The owner's latest explicit instruction supersedes the earlier source-selection
blocker and the intermediate QA-only proposal: TopStep live mirror is the common
application chart source. Personal NinjaTrader has priority; active chart-capable
trial/subscription users automatically use the mirror otherwise. Legacy source
policy flags no longer deny end-user mirror admission. No DEMO fallback is chosen.
Subscription expiry, revocation and chart capability remain enforced. Existing
single-hub gateway, source credentials and deployed hosting configuration remain
unchanged. This record attributes the product approval to the owner; it does not
claim an independent provider-contract verification.

Disposable Preview consumes the same market-data gateway adapter through its
existing parent-owned Local bridge. Only candle history and market WebSocket
paths are exposed; tokens are disposable, private alerts/accounts are excluded,
and Exit closes chart sockets and releases leases. Normal provisioning and trial
permissions remain the same as real accounts. There is no broad HTTP proxy.

Repository reference: `docs/architecture/MARKET_DATA_USER_ENTITLEMENT_STRATEGY.md`.
Earlier DEMO acceptance is historical and does not certify this live requirement.
No Server, Canary or Production changes are part of this task.

## Verification

209 tests passed across complete Preview, Social, model-inline and Aurora contract modules, including new regressions for real avatars, names, registration-only walls, session preservation, stale Preview ids and response/shutdown ordering. 105 additional chat/shared/market boundary tests PASS. Real browser acceptance is recorded at closeout. Previous full-regression counts remain bound to the previous code.
