# Aurora operator guide

История поправки: 2026-08-12T23:45:00Z; внёс `Grok 4.6 через Cursor по запросу owner`; scope: Environment Switcher default DEV/CANARY/PROD origins; Local DEV enabled only after loopback probe.
История поправки: 2026-08-12T22:30:00Z; внёс `Grok 4.6 через Cursor по запросу owner`; scope: live Production/Canary now serve Sign in/Register; promo/donation optional.
История поправки: 2026-08-12T22:15:00Z; внёс `Grok 4.6 через Cursor по запросу owner`; scope: primary Sign in/Register after mode-entry; promo/donation optional.

Актуально на 2026-09-01.

## Start and navigation

Run `start.ps1`. The launcher opens `/ui/`, where the user first chooses the
beginner or professional contour. Unauthenticated users then see Sign in /
Register (Telegram, Google, email). Promo code / donation is optional and must
not replace that primary account flow. The current runtime has no classic UI or
Telegram Mini App navigation. Historical classic reports are available only in
the separate read-only Legacy Viewer; see `../architecture/LEGACY_VIEWER.md`.

The top bar is shared by every page:

- NinjaTrader, Bridge and LM Studio show actual backend health.
- Market state and countdown use Pacific Time and CME daily/weekend pauses.
- The account chip selects any non-system account, including disconnected live
  accounts. Live remains read-only.
- The three-dot menu is personal: `Кабинет`, capability-gated `Admin Panel`,
  design settings and logout. System operations are not exposed there.
- `Кабинет` contains only profile and plan self-service. Users, monitoring,
  connectors, operations and other owner controls live in Admin Panel modules.
- A compact environment button appears only with `environment.switch`. It shows
  DEV / CANARY / PROD. CANARY opens `https://canary.stratforges.com` and PROD
  opens `https://app.stratforges.com` (defaults when the dedicated origin env
  vars are unset). Local DEV (`http://127.0.0.1:8765`) is enabled only after a
  successful credential-free loopback identity probe. Each target opens in a
  new tab without copying cookies, CSRF, tokens or browser storage. Ordinary
  users never see the switcher.

## Вход и общий чат

Каждый desktop-браузер имеет собственную Telegram-сессию. Если вместо чатов
виден экран входа, нажмите `Авторизоваться через Telegram` и отправьте боту
показанную команду `/login КОД`; открытие ссылки без параметра не является
успешным входом. После авторизации обновите страницу. Ошибка 401 больше не
стирает уже показанную историю.

Общий виджет называется `SF Chat`. В нём находятся и личные разговоры между
участниками, и прежние AI-диалоги; AI-собеседник по умолчанию — Виктор.
Технический `StratForge Orchestrator` остаётся внутренним AI gateway. Владелец
может напрямую вызвать Марину,
Толика, Никиту, Ивана или Управляющего по имени. Ответ `да`, `нет` или обычное
пояснение относится к последнему активному вопросу в этом же диалоге. Под
ответом показываются фактическая модель и проверяемые стадии действия:
`в очереди`, `выполняется`, `жду ваш ответ`, `нужно внимание`, `выполнено`.
Внутренние рассуждения модели не отображаются. Состояние Виктора, временные окна,
план на день/неделю и одновременно работающие агенты видны на странице Обзор.
Aurora и Telegram используют один `conversation_id`; поручение, уточнение и итог
не должны переходить в другой чат.
Финансовый ответ Марины всегда начинается с названия периода и точных дат
`from — to`; число операций без этой подписи нельзя сравнивать с другим экраном.

Community-профиль открывает тот же human conversation, что и глобальный SF Chat
launcher. Закрытие компактного уведомления справа внизу только скрывает карточку:
прочтение фиксируется при открытии диалога. Несколько сообщений одного диалога
группируются и показывают общий unread count. Fake online/presence не выводится.

## Community (`BETA` в Development)

Бренды: **STRATFORGE** — платформа, **SF Chat** — социальная и коммуникационная платформа: одно имя и для ленты с профилями, и для мессенджера. Переименование выполнено только в интерфейсе: маршруты `/api/community/*`, таблицы `sf_community_*`, миграции и внутренние идентификаторы `community_*` намеренно не трогались, чтобы не рисковать перед релизом.

Вкладка «SF Chat» содержит ленту, профили, подписки, поиск, сохранённые посты
и прежние workspace Channels. Privacy и block rules проверяются сервером. Для
изображений принимаются только PNG/JPEG/WebP до 2 МБ с проверкой file magic;
произвольные файлы не поддерживаются.

Кнопка «Результат» показывает только завершённые Demo/Backtest job текущего
пользователя и workspace. Метрики собирает сервер; введённый клиентом P&L
игнорируется. Strategy, Chart и Live result остаются выключенными, пока для них
нет отдельного server-attested adapter. Production-import выполняется только
dry-run/checksum workflow из `tools/community_storage_migration.py`: сначала
backup, затем exact checksum confirmation; исходные JSON не удаляются.

Владелец открывает `Admin Panel → Users and sessions → Детали`, чтобы увидеть активные
сессии и нагрузку вкладок. Там можно перезагрузить выбранную вкладку, немедленно
завершить одну или все browser-cookie сессии и запросить снимок экрана.
Те же действия доступны для самого владельца. ID в строке владельца — это ID
одного Telegram-аккаунта, а не отдельное устройство. Каждое устройство появляется в
живой телеметрии после обновления приложения; его можно назвать, например,
`Основной компьютер` или `Телефон`. Удалять аккаунт и подключаться заново для этого не нужно.
Пользователь сначала видит объяснение и кнопки разрешения/отказа, затем сам
выбирает экран, окно или вкладку в системном диалоге браузера. Без обоих шагов
снимок не создаётся. В чате доступны формы вроде `сделай скрин экрана
пользователю Dev` или `перезагрузи сессии пользователя ID 42`.

## Overview

Balance, strategy P&L and external cash movement are separate. The P&L curves
contain only closed attributed strategy trades after commission. NetLiq history
shows account value; funding/withdrawals are reported below and never added to
strategy performance. Daily/weekly/monthly rhythm and strategy sparklines make
direction and concentration visible.

## Backtesting

Select a catalog strategy, instrument, period, execution settings and parameters.
One instrument creates a job; a basket creates a batch. Opening a completed report
shows metrics, cumulative P&L, per-trade P&L, monthly result, price bars and the
trade table. Use `Шире`, `На весь экран` or drag the drawer's left edge on desktop.
Each completed report has a mini result curve. Hover over bar charts for the full
date/period and exact amount. Repeat/delete/cancel remain explicit confirmed actions.

## Trading and finance ledger

The strategy table hides personal/runtime-only classes by default. `Показать
скрытые / внешние` is diagnostic only. A managed strategy row opens its actual
runtime window, account, position, P&L, session history, parameters and warnings.
Red states require operator attention; an enabled strategy outside its configured
window is standby, not a failure.

`Журнал средств счёта` is the accounting source for non-trading cash movement:

- `Добавить движение` records a confirmed deposit/withdrawal/transfer/fee.
- `Импорт CSV` accepts `at_utc,kind,amount,note,source_id` and previews before
  import. `source_id` prevents duplicate statement rows.
- Unknown NetLiq deltas require evidence-based classification.
- Position-only fallback snapshots are ignored because they contain no balances.

Runtime enable/disable is guarded by the backend and is allowed only for paper
accounts. Live account controls are not offered.

## Performance

Choose period and account first. The CSV button exports exactly that scope. The
page separates strategy P&L, gross P&L, commissions, drawdown, account NetLiq and
cash events. It includes hourly, weekday, daily, weekly, monthly and direction
breakdowns, plus a paginated canonical closed-trade ledger. Click a trade for all
attribution and execution fields.

## Strategies

Portfolio cell IDs are immutable. Existing or archived IDs are never reused.
`Добавить инструмент` creates a new root block; `Добавить ячейку` appends one slot
and can accept an explicit 200/300/400-style ID. Opening a profile shows backtest
evidence separately from current runtime and actual annual trading. Notes persist
in the profile. Deletion, archive and NinjaTrader cleanup require confirmation.
AI-origin strategies and reports carry a visible `AI стратегия` badge.

## AI Lab

When LM Studio is stopped, use `Запустить окружение` on the page or in the system
menu. In lazy mode `run_allowed=true` is ready: a model loads on demand and is
reused during the run. Start creates one run only; duplicate start is blocked.

The run panel shows run ID, experiment, strategy/iteration progress, current stage,
elapsed time and heartbeat. Compile waiting is normal while NinjaTrader processes
automatic F5; stale heartbeat is highlighted. Model statistics distinguish API
success/latency from research outcome (terminal attempts, accepted candidates and
arbitration score). Exact token totals appear only when LM Studio returns `usage`.

At run end the configured cleanup may unload models and stop the model server.
That is expected; the next environment/run start restores it.

## AI Agents / API Keys

Open **AI Agents** from navigation. The basic form asks only for provider,
account/quota label, deployment/model, API key and (for Azure/Custom) endpoint.
Transport, auth and endpoint type are inferred. Roles, rotation pool and priority
are optional advanced settings; prices come from the central model catalog.
The key is stored through Windows DPAPI and only a mask is shown afterward.

For student credits, record the grant total and the current remaining amount from
the provider billing portal. Azure model keys cannot read Cost Management, so its
balance is a manual snapshot minus later StratForge calls. Deployment retirement
shown in Foundry is not the grant expiry. The tariff table is an estimator; the
provider invoice is authoritative.

Budget `0` is monitoring-only and does not block requests. A configured positive
daily/monthly/credit or `$0.50` single-call gate can block and disable the model.
Models sharing one provider/account share the same grant balance. Enabling a model
does not give it trading, Telegram or strategy
promotion rights; workflow integration is a separate reviewed change.

## Documents

Documents use the governance API. Editing requires actor and reason, has a dirty
guard and preserves history. Runtime defaults are read alongside governance text.

## Recovery

Фоновый watchdog устанавливается командой
`00_INSTALL_VITEK_BACKGROUND.cmd`. Он поддерживает backend, Telegram и
событийный worker без браузера. Лог: `logs/vitek-background.log`.
Для этого workspace запрещён встроенный браузер Codex; ручной визуальный smoke
выполняется пользователем в обычном браузере по
`http://127.0.0.1:8765/ui/`.

The pre-completion, final and prototype-cleanup backups are documented in
`UI_ROUTES_AND_ROLLBACK.md`. Do not use `git reset
--hard`: the worktree contains unrelated ongoing research changes.
