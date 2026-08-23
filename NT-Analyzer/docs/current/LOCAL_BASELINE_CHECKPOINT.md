# LOCAL baseline — ЗАКРЫТО

Дата: `2026-08-18` UTC. LOCAL приведён к canonical baseline и доказан после
перезапуска. Продолжать с раздела **«СЛЕДУЮЩЕЕ ДЕЙСТВИЕ»**.

## Ловушка, которую нужно помнить

`start.ps1` экспортирует `STRATFORGE_DEVELOPMENT_DATA_ROOT = <project>/data`.
Ad-hoc python без неё резолвит `<project>/data/development` — **другой**
`accounts.dpapi`, другие пользователи, брошенный с 3 августа. Первая версия
инвентаризации в этой программе прочитала именно его и выдала полностью ложную
картину (owner `2c347848…`, Telegram `999`, четыре `preview_*`).

**Любая проверка LOCAL обязана экспортировать переменные `start.ps1` либо
спрашивать запущенный сервер.** Признак подмены: owner без username или
пользователи, которых нет в `/api/auth/users`.

## Что было в живом LOCAL до очистки

7 аккаунтов, из них **два owner**: настоящий `1647145559` `dimon_check`
(uuid `6b0738c8…`) и синтетический `424242` (uuid `643f4ab5…`), плюс
`ARTUR_CA` и четыре `virtual_*` с фикстурными `google`/`test` identities.
Два owner-аккаунта — прямое доказательство того, что прежний `ensure_owner`
действительно создавал второго владельца.

## Что сделано

**Root cause (PR #126).** Владельца определяет неизменяемый UUID; Telegram,
Google, email — это identities этого UUID. `ensure_owner` больше не создаёт
второго владельца и не переписывает существующего молча: оба случая поднимают
`OwnerIdentityConflict` (409) с указанием конфликтующих значений.
`STRATFORGE_CANONICAL_OWNER_UUID` — конфигурация, не константа; тест
запрещает попадание реального UUID в исходники. 8 регрессионных тестов.

**Реконсиляция.** Backup живого store: `BACKUPS/local-live-store-20260818T060254Z`.
Сервер остановлен на время записи. Owner `6b0738c8…` → `eb9d8e32…`:
13 ссылок в auth document, workspace `ws_owner_training_c1fe3f2f8a52`
перевёден на canonical. Удалены 6 аккаунтов и 11 зависимых строк, затем
подчищены осиротевшие строки: 1 `trusted_device`, 2 workspace, 7 memberships,
принадлежавшие аккаунтам, которых уже нет.

**Канонический UUID** записан в `data/integrations/secrets.local.json`
(git-ignored, проверено `git check-ignore`), поэтому пустой store поднимется
как тот же владелец, а не как новый человек.

## Доказательство после перезапуска

```
users = 1            id=1647145559 dimon_check owner=True active
owner uuid           eb9d8e32-8db0-d590-9b35-ef1bd07ec61f
telegram identity    1647145559 (настоящая, сохранена)
orphan references    none (auth и workspaces)
identities unique    yes
второй owner         не восстановлен ensure_owner
```

Поверхности после рестарта: `/api/auth/me`, `/api/account/card`
(uuid canonical, 1 identity, 2 unbound client), `/api/workspaces` (1),
`/api/account/security` (2 device), `/api/admin/development-sync` = `current`
(running == head). LOCAL DB остаётся изолированной от Canary/Production.

## Новый Development checkpoint — TRIAL / MARKET-DATA / CONNECTOR OPEN

Ветка `codex/trial-connector-release-20260823` от `653f2b5b` реализует
защищённый вход без anonymous preview, один автоматический полный 7-дневный
trial, owner extension history и единый scoped HTTP/WS market-data admission.
После expiry аккаунт не блокируется; live charts допускаются через проверенный
user-owned provider/личный Connector либо продлённый trial вместе с обоими
explicit authority flags; shared owner feed остаётся fail-closed без отдельного
remote-server/redistribution authority.

Автоматический LOCAL checkpoint: `1943 passed`, `32 skipped`, `0 failed`;
custom suites `13/13`; bridge Debug build без предупреждений/ошибок; Python,
JavaScript, CSP, secret, Markdown/link, Context Pack и diff gates PASS. LOCAL
browser: два клиента MNQ/MES 5m, `10m56s`, точное совпадение WS price → close →
цветной rendered marker; `browser_ws=2`, `logical=4`, `wire=2`, общий
`signalr=1`, direct/auth/loginKey `0`, после закрытия browser/logical/wire `0`.
Ни Canary, ни Production не менялись. Следующий обязательный шаг — physical
NinjaTrader interaction и PR/CI; выпуск нового artifact пока не разрешён
фактическими acceptance gates.

## Предыдущий accepted checkpoint — BETA.29 RELEASE CLOSED

Реализованный market-data/chart baseline сохранён: TopstepX authentication,
ProjectX SignalR protocol, history/cache/failover/rollover и candle rendering
не рефакторились. Beta.29 исправляет только доказанные WebSocket close/refcount,
reconnect observability, bounded Operations probes и responsive layout defects.

Финальный LOCAL regression: `1924 passed`, `32 skipped`, `0 failed`; targeted
market/chart/Operations/responsive: `251 passed`. Load acceptance на трёх
browser profiles: 12 pages / 24 charts, peak `browser_ws=14`, `logical=22`,
`wire=2`, `signalr=1`; после закрытия `browser_ws=2`, `logical=4`, direct
provider/loginKey calls `0`. Responsive matrix: 84/84 checks, 2560×1440 →
360×800, whole-document overflow `0`.

[PR #142](https://github.com/OMNOM-111/NT-Analyzer/pull/142) прошёл все пять
mandatory CI jobs и слит в main как
`4d15f1d2250e2c52bde02b902d88ec7aad043543`. Из clean merge SHA собран один
signed immutable artifact `art_ccaadc3a536e4272809d32073f072918`: build
`sf-0.10.0-beta.29-4d15f1d2250e-20260823T020155Z`, archive
`882FF3520DDD43BF65925F3DFA5AA95DA56107336DA98EFDC64146A81981195B`,
runtime manifest
`CBA4FA70BD3868CBB80A8E8A42FE807B5401969CE09E1314671A73F51D132379`.

Canary deployment `dep_de061542f96641e1a10b7bb4456c2df0` прошёл owner
UI/Documents/36-chart/second-client acceptance. Production deployment
`dep_8716b7cf463f4cf8af092ba6a4e5bdae` продвинул тот же artifact без rebuild
и завершился `production_live`. На живом Production два клиента совпали по
MES/MNQ close и цветным live markers; MNQ 15m PASS; mobile/tablet document
overflow `0`. Production — единственный gateway hub, Canary и LOCAL —
consumers. Unrelated-user redistribution остаётся `EXTERNAL BLOCKED`.

Физическое enrollment нового NinjaTrader Connector остаётся отдельной
hardware-зависимой проверкой и не имитируется. Текущий Connector/NinjaTrader
не перезапускается без воспроизводимой необходимости.

Релизы только: `LOCAL → mandatory CI → PR → merge → immutable candidate →
Canary → acceptance → SAME artifact Production`.

Четыре Google/Resend secrets не ротировать.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-20T23:00:44Z | GPT-5.5 через Codex по запросу owner | Актуализирован LOCAL checkpoint: закрытые PR #130/#131/#135, fail-closed release decision и полная test-root isolation для final acceptance beta.28.
2026-08-21T02:52:33Z | GPT-5.5 через Codex по запросу owner | Добавлен фактический Canary PASS 2790fb43 и найденный в штатном promotion flow blocker approved_for_production; новый цикл обязателен, Production не менялся.
2026-08-21T03:50:00Z | GPT-5.5 через Codex по запросу owner | Закрыт полный release cycle merge 36600dba → signed artifact → Canary acceptance → same-artifact Production; market-data baseline сохранён.
2026-08-23T02:27:02Z | GPT-5.5 через Codex по запросу owner | Обновлён checkpoint после beta.29: чистый merge, зелёный PR #142, один immutable artifact, Canary/Production PASS, fan-out и responsive evidence.
2026-08-23T21:36:03Z | GPT-5.5 через Codex по запросу owner | Added the open Development trial/market-data/Connector checkpoint and its LOCAL automated evidence; beta.29 remains the unchanged live rollback-safe baseline.
2026-08-23T22:20:31Z | GPT-5.5 через Codex по запросу owner | Added clean 1943/32/0 regression and 10m56s two-client MNQ/MES browser fan-out evidence; retained the physical Connector and redistribution blockers.
-->
