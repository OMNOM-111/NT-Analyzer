# Phase 12 — Owner Acceptance Requirements Matrix

Integration branch: `release/0.10.0-next-architecture`.

**План/документ никогда не считается реализацией.** Легенда статусов:
`DONE (local)` — код + браузер-проверка + регресс-тесты локально; `FUNCTIONAL
PASS / DESIGN PENDING` — функциональная проверка завершена, финальную
визуальную приёмку выполняет owner; `DONE +
EXTERNAL` — локально сделано и проверено, реальная сквозная приёмка требует
внешней инфраструктуры/учётных данных владельца; `ARCH-ONLY` — заложена
архитектура/крючок, полный модуль намеренно вне охвата.

## Матрица требований

| # | Требование | Статус | Где сделано / как проверено |
|---|---|---|---|
| 1 | Компактный переключатель Local DEV / CANARY / PRODUCTION в верхней панели для `environment.switch`; расширенная страница остаётся в Админ-панели | DONE (local) | `ui.js` `wireAdminEnvironmentButton()` (сегменты DEV/CANARY/PROD, `#admin-env-switcher`), `theme.css` `.env-seg*`; браузер: сегмент DEV активен, CANARY/PROD переключают. Расширенная страница `showEnvironmentSwitcher` сохранена |
| 2 | Отдельные карточки устройств (компьютер/телефон/браузер/Connector): иконка, имя, онлайн, ОС, браузер/приложение, первый/последний вход, доверено/отозвано, «Подробнее»; внутренний `device_id` UUID (без «железного» ID), Connector — по installation ID; повторные сессии не дублируются | DONE (local) | Бэкенд уже на UUID + серверном fingerprint-дедупе (`security_devices.observe_session`); добавлен честный `online` из живых сессий (`_active_device_ids`, `_public_device`). Фронт: `securityDeviceRow` → `.device-card` с типом/иконкой/онлайн/ОС/first-last/деталями; `theme.css` `.device-*`. Браузер: 4 типа карточек, онлайн ● / офлайн ○, «Подробнее» показывает внутренний UUID |
| 3 | Разработка/QA на `127.0.0.1` без перевода сервера в staging: открыть приложение как владелец/разработчик/обычный/личный-NT/общий-NT + имитация Telegram/Google/e-mail; недоступно в Canary/Production | DONE (local) | `runtime_env.test_auth_enabled()`/`impersonation_enabled()` — default-on только в Development, невозможно вне неё; `test_auth.PRESETS` персоны `developer/ordinary/personal_nt/shared_nt` + `nt_mode`; QA-модуль `renderStagingInto`. Браузер: `/api/auth/test/status` enabled=true в dev, персоны открываются |
| 4 | Убрать «Войти как Claude/GPT/Вернуться к владельцу» из обычного меню владельца; управление служебными AI-аккаунтами — только в модуле «Разработка / QA» | DONE (local) | `ui.js` `wireTopbar` — из системного меню удалён `devServiceMenuItems()`; служебные входы перенесены в QA-модуль (`data-qa-svc`, `data-qa-return`). Браузер: меню владельца = Кабинет / Панель администратора / Настройки дизайна / Старый интерфейс / Выйти |
| 5 | Центр релизов: clean candidate → signed immutable artifact → real Canary deploy/checks/rollback; Production только после отдельного owner approval | BETA | Release Center завершил lifecycle на `7ebda6fa`: clean server-side build/signature verification, Canary blue-green, структурированные `pass`/`blocked` checks и реальный rollback `de7acaed` → re-promote `7ebda6fa`. Adapter `stage9_ssh` доступен для Canary; Production executor дополнительно закрыт process gate `STRATFORGE_RELEASE_PRODUCTION_EXECUTION=owner_approved` и в этой приёмке не включался. Evidence: `docs/changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md` |
| 6 | Верхний баннер обновления (предпросмотр) + сообщения «через 5 минут», «через 60 секунд», «обновление завершено»; без реальной отправки без Canary/Production | DONE + EXTERNAL | Бэкенд `release_center.notification_preview()` (kinds warn_5m/warn_60s/deploy_successful, `real_send_available=False`); фронт `showUpdateBannerPreview` (fixed top banner, тег ПРЕДПРОСМОТР), `theme.css` `.update-preview-banner`. Браузер: баннер «Обновление через 5 минут» вверху. Реальная отправка = EXTERNAL |
| 7 | Проверить UI привязки Telegram/Google/e-mail; при отсутствии реальных провайдеров не объявлять внешний вход PASS, дать локальную QA-симуляцию всех состояний + явную заметку про external acceptance | DONE + EXTERNAL | Кабинет → Безопасность → «Способы входа» (Привязать e-mail/Google, статусы verified); QA-модуль: панель «Способы входа — состояние и симуляция» с бейджами «реальный E2E: external» + привязка Google к виртуальным пользователям. Реальный сквозной вход = EXTERNAL, PASS не объявляется |
| 8 | Модель агентов: владелец+разработчики — полная команда; владелец может выдать `agents.team.full` другим; общий-NT — один координатор по умолчанию; заложить архитектуру под будущие имена/аватары агентов без полного конструктора | DONE (local) / ARCH-ONLY (конструктор) | `agent_allocation`: `grant/revoke/has_team_capability`, `resolve_allocation` (shared→один `Координатор`; grant→полная неадминистративная команда `TEAM_GRANTED_FULL`), эндпоинт `/api/owner/agents/team-grant`, клиент `ownerAgentTeamGrant`. `agent_display_config()` — крючок под имена/аватары, `editable=False` (полный конструктор вне охвата) |
| 9 | Финальная Development-проверка UI и принятого market-data/chart baseline; design acceptance остаётся owner gate | FUNCTIONAL PASS / DESIGN PENDING | На clean `7ebda6fa`, NinjaTrader OFF: MNQ 5m + MES 5m наблюдались `619.899 s` одновременно в in-app и Chrome. `44` observations, `0` grey/OFF/non-live; raw TopstepX = browser WS = last bar = rendered label на стабильных кадрах, оба направления green/red. Большой layout/fanout был проверен до release cut; exact artifact повторно подтвердил второй браузер. Cache-bust hashes сверены, stale service worker исключён. Evidence: `docs/changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md`. Финальная оценка spacing/hierarchy/design выполняется owner |

## Реальные внешние зависимости (НЕ настроены локально; PASS не объявляется)

Эти пункты реализованы в коде и проверены локально (dry-run/симуляция), но их
**реальная сквозная приёмка** требует внешней инфраструктуры или учётных данных,
которых нет в локальной среде:

1. **Реальный Telegram-бот** (боевой токен на окружение) — для настоящего входа
   через Telegram и доставки уведомлений. Локально: авто-вход владельца на
   loopback + имитация состояний.
2. **Google OAuth учётные данные** (`client_id`/`client_secret`/`redirect_uri`) —
   для настоящего входа/привязки через Google. Локально: test-auth имитация.
3. **Транзакционная доставка e-mail** — для реального кода на почту. Локально
   код виден в ответе test-auth.
4. **Отдельное Production approval** — Canary executor и реальный blue-green
   workflow доступны и приняты. Production promotion намеренно остаётся
   заблокирован отдельным owner confirmation и process-level gate; это не
   инфраструктурный дефект.

Пункты 6 и 7 сохраняют внешние зависимости для реальной доставки уведомлений
и Google/e-mail acceptance. Пункт 5 доступен в Canary; Production отдельно
owner-gated.
