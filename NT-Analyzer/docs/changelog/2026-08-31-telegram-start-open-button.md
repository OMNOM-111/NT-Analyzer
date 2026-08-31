# Telegram /start opens StratForge in the browser - 2026-08-31

Development status: implementation complete; not yet deployed to Production.

- A plain `/start` now answers with an inline **URL** button "Открыть StratForge"
  pointing at the environment's public origin (`https://app.stratforges.com/` in
  Production, `https://canary.stratforges.com/` in Canary).
- The button is deliberately a Telegram URL button, never a Web App button: the
  retired Mini App container must not return through the bot. The URL is the
  site root, not the old `/ui/` Mini App entry point.
- Development has no public origin, so it sends no button rather than a loopback
  link Telegram would reject.
- Telegram login, login confirmation, NinjaTrader confirmation and notifications
  are unchanged; they keep using `callback_data`, never `web_app`.
- No legacy Mini App route or mirrored UI is restored.

## Production rollout order

The bot's `web_app` menu button must be replaced **only after** this version is
live in Production, otherwise the old button is gone while the new `/start`
button does not exist yet. Sequence:

1. Deploy this change to Production.
2. Verify a plain `/start` returns the URL button.
3. Call `setChatMenuButton` with `{"type": "default"}` to drop the Mini App
   button, and register `/start` via `setMyCommands`.

Note: Telegram's chat menu button supports only `commands`, `web_app` and
`default` - there is no URL menu-button type, so the normal link lives in the
`/start` reply rather than in the menu button itself.
