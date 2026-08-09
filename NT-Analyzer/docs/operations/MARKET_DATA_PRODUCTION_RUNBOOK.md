# Market-data production runbook (draft)

Date: 2026-07-16

История поправки: 2026-08-09T00:57:35Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: TopstepX read-only provider, независимая работа графиков и Production acceptance-gates.

## Status gates

| Gate | Meaning |
|---|---|
| CORE IMPLEMENTATION COMPLETED | code + unit tests |
| DEPLOYED | Bridge DLL installed + backend restarted |
| ACCEPTANCE PASSED | visual checklist signed |
| 100-USER LOAD PASSED | load report |
| PRODUCTION FAILOVER COMPLETE | licensed live external + NT stop |

## Независимый read-only поток TopstepX

TopstepX используется только в display data plane: contract search, OHLCV bars
и realtime subscription. Account/order/trade API не вызывается; execution и
strategy authority остаются NinjaTrader-only.

1. Получить письменное разрешение на remote-server use и показ/redistribution
   данных пользователям либо выбрать лицензированный server-side feed.
2. Передать username и API key в защищённый secret provider, не в Git и не в
   чат. Старые имена `NTA_TOPSTEP_USERNAME`/`NTA_TOPSTEP_API_KEY` читаются для
   совместимости, канонические — `NTA_TOPSTEPX_USERNAME`/`NTA_TOPSTEPX_API_KEY`.
3. Выбрать `NTA_TOPSTEPX_DATA_MODE=sim|live`; значение обязано соответствовать
   доступу TopstepX.
4. Только после пункта 1 включить оба policy-gate:
   `NTA_TOPSTEPX_REMOTE_SERVER_AUTHORIZED=1` и
   `NTA_TOPSTEPX_REDISTRIBUTION_AUTHORIZED=1`.
5. Проверить status: credentials present, provider initialized, auth success,
   active/exact contract search, bars, SignalR health/reconnect. Корневой запрос
   (`MNQ`) обязан разрешаться в `activeContract` ProjectX без каталога
   NinjaTrader. Readiness становится зелёным только после реального bars-call;
   на закрытом рынке успешный stale-ответ доказывает доступность провайдера, но
   сам chart payload всё равно не помечается как `live`.
6. Остановить/отключить NinjaTrader и доказать, что chart payload остаётся
   `live=true`, source provider — `topstepx`, execution source — `ninjatrader`.

Любой пропущенный пункт — `BLOCKED`, а не «TopStep настроен». Ошибки провайдера
не должны давать право на сделку: последний снимок можно показать только как
offline/stale, а backend после короткого cache TTL повторяет независимый feed.

## Deploy Bridge

1. Stop chart load if needed (optional).
2. Backup `%USERPROFILE%\Documents\NinjaTrader 8\bin\Custom\NTAnalyzerBridge.dll`.
3. Copy `bridge/bin/Release/NTAnalyzerBridge.dll` over Custom.
4. Restart NinjaTrader (AddOn reload).
5. Confirm `data/runtime/market_data_ipc_bridge_metrics.json` updates.
6. Confirm backend log: `market-data IPC listening on 127.0.0.1:18765`.

## Browser WS

- URL: same-origin `ws(s)://{host}/ws/market-data`
- Never point browsers at Bridge `127.0.0.1:18766`.
- Cloudflare Tunnel must forward WebSocket upgrades for `/ws/market-data`.

## Rollback

1. Restore `.bak-*` DLL.
2. Restart NinjaTrader.
3. Set `NTA_DATA_PLATFORM=memory` if Redis/PG misbehave.
4. HTTP `/bars/batch` + `market_bars.json` remain emergency fallbacks.

## Diagnostics

- `GET /api/ops/runtime/market-data/diagnostics`
- `GET /api/integrations` — secret-free TopstepX config/provider/health и точные
  `blocking_reasons`;
- `GET /api/ready` — первый запрос запускает неблокирующую provider-проверку;
  до успешного bars-ответа возвращается `provider_probe_pending|failed`, а не
  ложный `ready` по одному наличию credentials;
- Per-chart title: `LIVE|DEGRADED|STALE · provider · contract · WS|HTTP · age · #hash`
