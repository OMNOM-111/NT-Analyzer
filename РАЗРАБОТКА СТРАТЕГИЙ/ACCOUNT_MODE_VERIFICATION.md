# Проверка гипотезы: DEMO vs LIVE и баланс на счету

Документ фиксирует, как именно UI/backend/bridge определяют режим и баланс
аккаунта NinjaTrader, и что произойдёт, когда пользователь переключит NT с
демо на реальный счёт.

## TL;DR

Гипотеза пользователя **подтверждена**:

1. Сейчас NinjaTrader подключён к демо-счёту `DEMO3369390`. Bridge корректно
   отдаёт по нему `cash_value = 50173.5`, `net_liquidation = 50173.5`,
   `connection_status = "Connected"`. Это и есть реальный баланс демо-счёта.
2. Когда пользователь переключит NinjaTrader на свой реальный (live) счёт и
   тот окажется в состоянии `Connected`, bridge **сам пометит** его
   `account_mode = "live"` и **сам подтянет** реальный broker balance из
   NinjaTrader API. Никаких ручных переключателей в нашем UI не требуется.
3. Live-аккаунт `1267509` сейчас показывает `0`, потому что он
   `Disconnected` — это не значит "счёт пустой", это значит "NT сейчас
   не залогинен в этот счёт у брокера". Как только подключение появится,
   баланс заполнится автоматически.

## Где это решается в коде

### Bridge (NinjaTrader AddOn, C#)

Файл: `bridge/src/Runtime/RuntimeTelemetryExporter.cs`,
метод `ClassifyAccountMode(name, acc)` (около строки 560):

```csharp
// Try Account.Provider (NinjaTrader API)
string provider = GetStringProp(acc, "Provider");
if (!string.IsNullOrEmpty(provider)) {
    string p = provider.ToLowerInvariant();
    if (p.Contains("playback")) return "playback";
    if (p.Contains("simulator") || p.Contains("sim")) return "paper";
}
// Fallback: by account name
string n = (name ?? "").ToLowerInvariant();
if (n.Contains("playback")) return "playback";
if (n.StartsWith("sim") || n.Contains("paper") || n.Contains("demo")) return "paper";
if (string.IsNullOrEmpty(n)) return "unknown";
return "live";
```

Из этого следует:

- Любой аккаунт, чей **Provider** в NinjaTrader = Sim/Simulator/Playback,
  получает mode `paper` / `playback`.
- Аккаунты с именем, содержащим `sim`/`paper`/`demo`/`playback`,
  принудительно классифицируются как paper/playback независимо от
  провайдера.
- **Любой остальной аккаунт автоматически считается `live`.** То есть
  реальный broker account (например, AMP, NinjaTrader Brokerage, Rithmic с
  настоящим логином) попадёт в `live` без каких-либо настроек с нашей
  стороны.

Баланс `cash_value`, `buying_power`, `net_liquidation`, `realized_pnl`,
`unrealized_pnl` берутся напрямую из NinjaTrader API
(`Account.Get(...)`), то есть это всегда то, что брокер сообщил NT для
этого счёта. Для `live` это реальные деньги, для `demo`/`paper` это
виртуальные деньги симулятора.

### Backend (Python, app/runtime.py)

`_classify_account_mode(name, declared)` (около строки 152) **доверяет**
полю `account_mode`, которое пришло от bridge. Дополнительные имя-эвристики
включаются только если bridge не указал режим. То есть:

- Если bridge сказал `live` — backend считает `live`.
- Если bridge сказал `paper` — backend считает `paper`.
- Имя-эвристики (paper/demo/live/playback) — это только страховка на случай
  старого bridge без поля `account_mode`.

`is_live` устанавливается, если итоговый mode == `"live"`. Для всех
`is_live` аккаунтов backend и UI отказываются принимать команды управления
стратегиями (read-only).

### UI (app/static/trading.js, trading.html)

После Phase 19+hotfix2:

- В верху правой панели "Настройки торговли" появилась карточка
  `#acct-headline`, которая большим бейджем показывает текущий режим
  выбранного аккаунта:
  - `DEMO` — зелёный бейдж, для аккаунтов с `demo` в имени.
  - `PAPER (SIM)` — зелёный, для Sim/Simulator.
  - `LIVE` — красный, для реальных брокерских счетов.
  - `PLAYBACK` — жёлтый, для Playback101.
- Сразу под бейджем — крупная сумма `cash_value` (или `net_liquidation`,
  если cash отсутствует) и валюта.
- Ниже мелкой строкой: Cash / NetLiq / Real PnL / Unreal PnL.
- Если выбран live — показывается замок "🔒 LIVE — реальные деньги.
  Управление из этого UI заблокировано".
- Если NT отключён от аккаунта (`Disconnected`) — баланс показан серым
  с подписью "(stale, NT disconnected)" и появляется предупреждение
  "⚠ NinjaTrader не подключён к этому аккаунту".

Карточка обновляется на каждом цикле опроса
`/api/ops/runtime/accounts` (~5 секунд), поэтому переключение NT с
demo на live видно в браузере без перезагрузки.

## Сценарий проверки на реальном live-аккаунте

1. Сейчас: NinjaTrader в demo. UI должен показывать большой зелёный бейдж
   `DEMO`, имя `DEMO3369390`, баланс `+50,173.50`, статус `● CONNECTED`.
2. Залогиниться в NinjaTrader в свой live-аккаунт (например, `1267509`),
   убедиться что в NT справа внизу статус Connected.
3. Подождать ~5 секунд (или нажать F5 на странице торговли).
4. Ожидаемое поведение UI:
   - Карточка `#acct-headline` переключается на красный бейдж `LIVE`.
   - Имя аккаунта меняется на `1267509`.
   - Сумма обновляется до реального broker balance.
   - Появляется предупреждение "🔒 LIVE — реальные деньги. Управление
     из этого UI заблокировано".
   - Live-аккаунт **не появляется** в dropdown "Аккаунт NinjaTrader" для
     запуска стратегий, а отображается отдельной locked-карточкой
     `#live-accounts-info` ниже.
   - Все кнопки Start/Stop/Update заблокированы на любом уровне (UI,
     backend, bridge).
5. Вернуться обратно в demo → бейдж снова DEMO, баланс снова 50,173.50.

Если что-то из этого не сработало — нужно проверить:
- `data/runtime/accounts.json` — что там реально для live-аккаунта
  (`account_mode`, `cash_value`, `connection_status`).
- Возраст `heartbeat.json` — bridge мог перестать обновлять файлы.
- Бейдж версии trading.js в DevTools (`v=20260502-phase19-hotfix2`),
  чтобы исключить старый кеш.

## Почему `1267509` сейчас показывает 0

В текущем `accounts.json` он помечен как `connection_status: "Disconnected"`
и `cash_value: 0`. NinjaTrader не отдаёт балансы для аккаунтов, в которые
не залогинен — это поведение NT API, не баг бриджа. Как только пользователь
залогинится в live-аккаунт у брокера, NT начнёт отдавать настоящий
balance, и bridge запишет его в accounts.json.
