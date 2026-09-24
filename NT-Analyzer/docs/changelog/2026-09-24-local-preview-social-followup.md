# Local Preview exit, public profiles and model sharing visibility

Status: BETA — canonical common TopStep mirror and scoped manual Local acceptance PASS; full regression reconciled PASS; owner review and remote CI are separate.
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
The read-only chart lease follows the active Preview process, rechecked every
15 seconds, rather than inheriting the separate 30-minute paid-model-call limit.
Exit closes it immediately; child-side trial/subscription revalidation remains.

Repository reference: `docs/architecture/MARKET_DATA_USER_ENTITLEMENT_STRATEGY.md`.
Earlier DEMO acceptance is historical and does not certify this live requirement.
No Server, Canary or Production changes are part of this task.

## Verification

209 tests passed across complete Preview, Social, model-inline and Aurora contract modules, including new regressions for real avatars, names, registration-only walls, session preservation, stale Preview ids and response/shutdown ordering. 105 additional chat/shared/market boundary tests PASS. Real browser acceptance is recorded at closeout. Previous full-regression counts remain bound to the previous code.

## Additional defects found in the real browser walkthrough

- A first-ever Desktop deliberately created an empty layout. It now uses the
  existing chart-opening path to show a live chart immediately; a saved layout
  that the user emptied intentionally stays empty.
- The Local owner's five index charts resolved through an older upstream catalog
  to September contracts with no live bars. The existing Local front-month
  overlay was refreshed for MES/MNQ/RTY/M2K/MYM only after the same gateway
  returned real December one-minute candles for each at 2026-09-24T03:14Z.
  The original overlay is preserved in a local artifact, never committed.
  A bare-root history miss can retry that existing catalog's current contract;
  explicit fixed historical contracts are never silently substituted. No new
  provider connection or server change is involved.
- Social now also uses the linked Google profile name when account first/last
  name is empty, then the public handle, while preserving user-chosen names.
- Preview run on 5292a2ec: actual MBT candles painted, eight public owner/organization
  posts visible, actual owner avatars loaded, private wall excluded, registration
  milestone present without an empty-wall message. One Exit action returned to
  the owner index at 8765 without a login or Preview loop; console errors absent.
  The final fresh-run acceptance is recorded below.
- Additional focused regressions: 70 PASS (gateway, access, Preview parity,
  first Desktop and chart template). Final regression is recorded below.

## Final manual Local walkthrough

Implementation/runtime: clean `003e00d1d95ecc7e04c679fda26bf8c27d50f221`,
`dev-0.10.0-beta.96-003e00d1d95e`, Local 8765. Final documentation closeout
does not rebuild or restart this tested runtime.

- A new user was created through the real Developer Preview picker and normal
  Professional trial choice, with its own workspace and five active trial hours.
  First Desktop opened an actual MBT chart automatically. Live candles and
  changing price were visible; no DEMO source or stream error. Owner Desktop
  painted all five current RTY/MES/MNQ/M2K/MYM December charts before and after QA.
- Models showed empty **My models** separately from available shared Gemini.
  The exact first connection showed inline checking, then a real successful
  model response. The owner table showed two shared connections and private
  labels on the others without opening cards.
- Three normal Chat turns (greeting, capabilities, order-type question) produced
  conversational Deputy replies. Only the explicit checklist commission created
  a work task, persisted result and review actions. The current Deputy avatar
  served as the speech control, with completed playback state and no separate
  speech button. Audible output was not independently recorded. Memory remained
  empty; Tasks contained only this user's check and commission.
- Owner usage separately showed five Preview calls, 1530 input / 274 output
  tokens and the configured free-model cost. With the Preview card already open,
  owner sharing OFF refused the next call: "Владелец закрыл доступ к модели."
  Successful usage stayed at five. Sharing was restored to its original ON.
- Social showed all eight public owner/organization posts and loaded owner
  photos. This owner's account name fields are empty, so its actual public
  handle is used; no person's name was invented. Private wall entries were
  absent. Two disposable posts appeared newest-first above registration and
  were visible to the owner as TEST/PREVIEW. No empty-wall invitation appeared.
- TopStep opened its existing development scaffold; Documents rendered the
  product Charter. No unexpected console errors occurred in the checked flow.
- One Exit returned directly to the original owner at `/ui/index.html`, without
  login or a Preview loop. The disposable container and both posts disappeared.
  The parent retained a `test-preview` / `preview_exit` receipt at
  `2026-09-24T03:39:07Z`; private data was not retained in that receipt.
- Original owner access projection stayed exactly equal before/after: two
  users, one workspace, three memberships; SHA256
  `dfcdf0b471112eb88388f3651350b5a5efb6082c172935de1209658af3011ccd`.
  The verified front-month overlay update is an intentional Local source-config
  correction, not a temporary permission change. Other pre-existing runtime
  data and unrelated Preview directories were not removed.
- Final related whole-module suite: **507 PASS**. Root secrets scan PASS;
  646-file bundle passed all four artifact-content gates. Full native Windows
  regression and the independent legacy runner are reconciled below.

## Final verification and operational closeout

- Final runtime code: `56945ac68e94cb7ffa031ef2312dec5a9ad80a54`, clean
  detached Local checkout, build `dev-0.10.0-beta.96-56945ac68e94`. This adds
  only the Preview chart-lifetime correction above the full browser walkthrough.
  Its complete affected-module rerun passed **42 tests**, including a simulated
  active session older than 30 minutes and refusal after the child exits.
- A third fresh Preview on that code again opened real MBT candles automatically
  (LIVE TopstepX/WS, last observed tick 2026-09-24T03:52:57Z), with no console
  errors. Chart maximize worked. The browser-control tool then stopped answering
  two commands during restore/minimize verification; that final interaction is
  not counted as PASS. No browser/application root cause is asserted.
- The last disposable child was identified by its exact Local parent, listener
  and Preview id, then stopped. The existing parent lifecycle closed the bridge,
  retained the minimal deletion receipt and removed its container. No owner
  session was replaced. The earlier complete one-click Exit walkthrough remains
  valid for unchanged Exit code; the last cleanup is explicitly a recovery path.
- Full native Windows inventory: **293 files / 6214 cases; 6080 passed,
  134 skipped, zero unresolved failures**. Four disjoint whole-file partitions
  plus complete affected-module reruns cover the final code. This is not one
  unchanged-tree run. One source-introspection check crossed an edit; one
  unrelated temporary queue-directory rename returned WinError 5. Their complete
  modules passed on stable reruns (12 and 17 tests). Three newly added cases were
  covered by complete final-module reruns. Counts exclude duplicate passes.
  Evidence: local `.artifacts/mirror-full-regression/reconciled-result.json`.
- Independent legacy runner: **13/13 suites PASS** on complete rerun after one
  temporary fixture file rename failed. No trading/queue implementation was
  changed to hide that transient failure. Related whole-module suite: 507 PASS.
- The final runtime's 646-file artifact-content rehearsal passed all four gates;
  root secrets scan and External GPT Context validation passed. Final docs-only
  closeout is checked again without changing the running code.
- Scope is Local only. The front-month overlay correction is preserved, owner
  sharing is restored, and created test identities/containers are no longer
  active. No Server, Canary, Production, real trades, merge or promotion.

IMPLEMENTATION COMPLETE for this scoped Local follow-up. Git closeout continues
the existing draft PR #291. STAGE CLOSED means this Local engineering scope;
owner acceptance, remote CI and the whole Agent World program are separate.
