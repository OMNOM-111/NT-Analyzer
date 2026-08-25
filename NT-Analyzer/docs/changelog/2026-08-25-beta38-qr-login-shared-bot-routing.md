# Beta.38 QR Login, Canonical Owner and Shared-Bot Confirmation Routing

- Date: 2026-08-25 UTC
- Author: Claude Opus 5 через Claude Code по запросу owner
- Clean beta.38 SHA: `39c00b83d8ad02b0d72b1845f2d575c93f08d465`
- Status: `BETA.38 CANARY ACCEPTED / PRODUCTION LIVE`
- Production before: `0.10.0-beta.29` → `0.10.0-beta.33` → `0.10.0-beta.38`

## Canonical owner is a person, not an environment variable

Telegram login decided ownership by comparing a chat id against
`NTA_TELEGRAM_CHAT_ID`. Where that variable was not exported — the Canary and
Production shape — the canonical owner resolved as an ordinary verified human,
ran the registration-trial branch and was greeted with a 7-day trial (beta.29
wording: `Free Preview`). The same path minted a fresh UUID for an owner the
deployment already named, which is how one human acquired different identities
per environment.

`owner_claim()` is now the single authority for every provider: the stored row,
then the configured canonical UUID, then a provider identity linked to that
UUID, and only then the legacy chat-id comparison. A recognised owner keeps the
canonical UUID, an account a previous environment demoted is adopted back with
its stale trial outbox cleared, and `_primary_owner_row()` prefers the canonical
UUID so LOCAL opens as exactly the owner the servers resolve. The entitlement
layer already refused trials for owners, so correcting resolution fixed UI, API,
capabilities and bot wording together.

Verified identical in all three environments: `eb9d8e32-8db0-d590-9b35-ef1bd07ec61f`,
`role=owner`, `entitlement=founder`, `trial_access=owner/unlimited`.

## Login is a QR and one confirmation

The previous flow opened a popup window that browsers block, then demanded a
Telegram contact upload on every login. Both are gone.

The QR carries `tg://resolve?domain=<bot>&start=<payload>`. The https `t.me`
form was tried first and rejected on real hardware: the iOS Camera app does not
honour Universal Links, so scanning it opened Safari and the user had to
continue into Telegram by hand. The custom scheme is resolved against the
installed app on iOS and by intent on Android. Because a scheme is a dead end
without Telegram installed, the https link is rendered directly under the QR and
remains the anchor href and the desktop fallback.

The QR encoder is `app/qr_code.py`: byte mode, level M, versions 1–10, all eight
masks. The backend stays stdlib-only and the strict CSP has no external asset to
block. It was verified bit-for-bit against a reference encoder across versions
1–10 during development; that reference is not a runtime or test dependency. Two
spec defects were found that way — format bits placed LSB-first, and the second
format copy split 8/7 instead of 7/8, overwriting the permanently dark module.
The committed tests round-trip a finished matrix back to its payload.

## Opening a challenge no longer spends it

Claiming required status `created` and moved straight to awaiting-confirmation,
so merely opening the deep link consumed the challenge: reopening the same QR
was answered "истекла или уже использована" although nobody had confirmed
anything, and because every refusal shared that sentence a genuinely new attempt
on a second computer looked like it had inherited the previous expiry.

The lifecycle is now explicit: `pending → opened → confirmed → consumed`, with
`cancelled` and expiry as distinct terminal states. Opening is repeatable for the
whole TTL and mutates nothing another attempt can observe; only the confirmation
spends the challenge, exactly once; a challenge opened by one Telegram account
cannot be taken over. Refusals name the actual cause. TTL is 10 minutes, because
three was not long enough to find a phone and open a camera.

## The confirmation had to cross an environment boundary

A tapped inline button sends a `callback_query`, which carries no message text.
One Telegram bot serves every environment and Production owns its updates, and
that routing decision reads message text. Worse, Production was running beta.33,
which contains no login callback handler at all — the flow was added in beta.34
and deployed only to Canary. Every tap therefore arrived at Production, matched
nothing, and was dropped without a state change, without a forward and without
an `answerCallbackQuery`: the button did nothing and the browser waited forever.

Stamping the environment into `callback_data` could not fix this, because the
code reading the stamp would itself have to be on Production — a deadlock, since
the flow could not be accepted on Canary until Production shipped it.

So the confirmation stopped using callbacks. A tapped reply-keyboard button
sends its own label as an ordinary message, and message text is the one thing
the deployed Production already routes between environments — it is how
`/login [CANARY] CODE` has always worked. Running beta.33's own routing function
verbatim against the live Canary label returns `canary`, so the tap reaches the
environment that owns the challenge with no Production deployment required.

## LOCAL logout

Development signs the canonical owner in whenever no session cookie is present,
so logout cleared the cookie and the next request signed the owner straight back
in: the login screen was unreachable and the QR flow could not be tested on
LOCAL at all. Logout now records an explicit development-only "stay signed out"
hold that a real login clears. Guarded by `is_development()`, so Canary and
Production cannot grow a logged-out mode.

## Acceptance

Owner physically scanned the Canary QR on iPhone, Telegram opened directly,
tapped `Подтвердить вход`, and the waiting Canary browser authenticated
automatically with no reload and no contact upload.

Machine evidence: three concurrent attempts on Canary and Production produced
3/3 unique challenges, each independently `created`; repeated polling consumed
nothing; a fresh attempt inherited no state; an unknown challenge returned 410;
the served QR SVG decoded back to exactly the issued deep link; readiness
`20/20`; chart assets byte-identical to the clean SHA; Production market data
settled to `external_live / LIVE / fresh`.

Full regression `2007 passed`, `32 skipped`, `0 failed`. PRs #150, #151, #154,
#155, #156, #157, #158, #160, #161 each passed all five mandatory CI jobs.

## Release identity

| Environment | Version | Build | Runtime artifact SHA256 |
| --- | --- | --- | --- |
| Canary | `0.10.0-beta.38` | `sf-0.10.0-beta.38-39c00b83d8ad-20260825T173719Z` | `BDCD96CEA12E4AEF0435A99C314AE7EE52F381DE766CD0C975A8212FF878D530` |
| Production | `0.10.0-beta.38` | same build, same artifact, promoted without rebuild | same |

- candidate `rc_dbd76fe013c341c382a3fe2b3b9fb5e8`
- artifact `art_a426dbe3ae214d8a9854e9e92d052b31`
- archive SHA256 `F0FDC106001AAAA4A79735F08DD388D02848597B2A850E8AB6A643262F22766A`

## Open items

- Production `/api/admin/connectors` connector probe exceeds its 3s budget and
  returns `partial=true` with `unavailable_sources=[connector]`. Diagnostics
  only; enrolled connectors and NinjaTrader are unaffected, and LOCAL reports
  `healthy 1/1 online` with a fresh heartbeat.
- Production `active_workspace.entitlement_id` reads `stage9_canary_acceptance`,
  a stale workspace label. The effective plan is `founder`, so access is correct.
- Four previously disclosed Google/Resend secrets remain unrotated by explicit
  owner decision; rotation stays the final security closeout.
