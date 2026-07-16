# StratForge — ЗАДАНИЕ ДЛЯ РАЗРАБОТЧИКОВ

**Дата:** 15 июля 2026  
**Проект:** `NT-Analyzer` (Aurora / StratForge)  
**Файл:** один главный документ. Передавать разработчикам целиком.  
**Проверено по коду проекта** (не абстрактное ТЗ).

---

## АУДИТ СТАТУСА (15 июля 2026)

Легенда: ✅ код+автотесты (формальная приёмка владельцем — отдельно) · 🟡 частично · ❌ не начато · ⚪ ждёт владельца

> **Важно:** проценты ниже — статус **реализации в рабочей копии** (код+pytest), не финальная приёмка A–D владельцем. Ручной staging E2E и Google OAuth secrets остаются у владельца. Шапка и тело пунктов синхронизированы 15.07 (после аудита фикса Work 5).

| # | Работа | Статус | Комментарий аудита |
|---|---|---|---|
| 1 | Админка сессий и ресурсов | ✅ ~95% | Monitoring tab, admin-kill code `session_admin_revoked`, telemetry note, auth sessions overview. Consent-скрин без silent stream. Остаток: ручной прогон owner UI на живом сервере. |
| 2 | Живая демоверсия вместо blur | ✅ ~90% | `demo_backtest` capability, 1-click сценарии, watermark, quota 3/день, без NT. Остаток: ручной UI-прогон free user. |
| 3 | Учебная торговля | 🟡 UX-fix | **Wallet-first:** сначала только сумма депозита; после — терминал как TopStep (графики/ордера/позиции/PnL/риск), деньги виртуальные. 6/8 charts — не MVP. |
| 4 | Сообщество | ✅ ~80% | `community.py`, страница, chat/publish/copy/ratings/moderation. Telegram duplicate через `NTA_COMMUNITY_TELEGRAM_CHAT_ID` (отдельно от Orchestrator). |
| 5 | Telegram + Google для NinjaTrader | ✅ ~95% | Вход — только Telegram. Google + Telegram step-up — только для NT. Gate: public `google_linked` **и** store-lookup `google_sub` по `user_id` (forged flag → 403). Ручной OAuth — ⚪ секреты владельца. |
| 6 | Staging + «войти как» | ✅ ~90% | `runtime_env`, `test_auth`, presets, impersonation + red banner, prod lock на старте, `docs/STAGING_QA.md`. |
| 7 | Micro Live | ✅ ~85% | MVP free trades + scale 1:100; staging stubs. |
| 8 | Рейтинги ИИ ★ → routing | ✅ ~90% | Агрегаты + router exploration после gates. |
| 9 | Режимы Новичок / Профессионал | ✅ MVP | **Фаза E.** `ux_mode`, экран выбора, nav/API deny beginner, смена режимов §9.0, owner=professional, staging presets, `tests/test_ux_mode.py`. |

**Фазы:** A–E MVP в коде · **доработка UX учебной торговли (wallet-first / TopStep-like desk) — в работе.**

**Замечание по аудиту Work 5 (~35%):** внешний аудит сравнивал со *старым* ТЗ «Google обязателен для всего приложения». Владелец уточнил: Google только для NinjaTrader. По актуальному ТЗ Work 5 принят; критическая регрессия bridge pair устранена.

**Автотесты (15.07.2026, после Фазы D):** `test_phase_a_auth` + `test_demo_backtest` + `test_practice_trading` + `test_community` + `test_phase_d` + `test_permissions` + `test_cabinet` + `test_account_auth` + `test_admin_journal` → **62 passed**; `test_chief_agent` → **96 passed**.

**Что можно не переделывать с нуля:** сессии/телеметрия/скрин/journal; Telegram login; Orchestrator + ★ UX; Desktop charts; full backtesting UI (paid/owner); Topstep status scaffold; staging/test-auth/impersonation/Google link слой; demo/practice/community/micro-live контуры; AI star aggregates + routing hook.


---

# ЧАСТЬ 0. ЧТО НУЖНО СДЕЛАТЬ В ПРИЛОЖЕНИИ

Необходимо доработать наше приложение StratForge. Ниже — полный список того, что конкретно нужно реализовать.

## Короткий список (8 больших работ)

1. ✅ **Админка сессий и ресурсов** — Monitoring tab, kill + сообщение пользователю, consent-скрин, browser telemetry, journal.
2. ✅ **Живая демоверсия** — demo-tier вместо blur: 1-click бэктест, watermark, CTA.
3. 🟡 **Учебная торговля** — virtual account, ticket, layouts 1/2/4, risk lock, отчёты; **онбординг: сначала только виртуальный депозит**, затем полный терминал.
4. ✅ **Сообщество** — chat / publish / copy / ratings; Telegram duplicate отдельным chat_id.
5. ✅ **Google + Telegram step-up для NinjaTrader** — вход по-прежнему только через Telegram; Google и повторное подтверждение в Telegram нужны лишь для подключения/управления NT (Pro/dev тоже). Остальной функционал без Google.
6. ✅ **Режим «войти как пользователь»** — staging + virtual users + impersonation + banner + prod lock.
7. ✅ **Micro Live (реальные деньги в уменьшенном масштабе)** — 5 free trades → scale 1:100 + comparison PnL; staging stubs; страница + capability.
8. ✅ **Рейтинг ИИ по трём звёздам** — агрегаты role/model/role+model; admin tables; routing с exploration без обхода gates.
9. ✅ **Режимы «Новичок» и «Профессионал»** — выбор при старте определяет весь интерфейс и доступный функционал (см. ПУНКТ 9). *(MVP Фазы E)*

## Порядок работ (обязательный)

Делать строго по фазам, иначе сломается прод или нельзя будет проверить UX.

| Фаза | Что делать | Зачем сначала | Статус аудита |
|---|---|---|---|
| **A** | Staging + NT dual-auth (Google+TG step-up) + «войти как» + сессии | Проверка UX и безопасный NT-доступ | ✅ ~95% |
| **B** | Демо вместо blur + учебная торговля | Чтобы новым пользователям было что трогать | ✅ ~85–90% |
| **C** | Community | Социальная площадка после базового доступа | ✅ ~80% |
| **D** | Micro Live + умный AI-routing по ★ | Реальные микроденьги и автоулучшение ИИ | ✅ ~85–90% |
| **E** | Режимы Новичок / Профессионал | Развести простой демо-трейдинг и pro-контур стратегий/ИИ/NT | ✅ MVP — код + `test_ux_mode.py` |

---

# ЧАСТЬ 1. ЧТО УЖЕ ЕСТЬ В ПРОЕКТЕ (чтобы не делать заново)

Перед работой разработчик обязан открыть эти файлы и понять текущее состояние.

> **Аудит 15.07.2026:** таблица ниже подтверждена. Колонка «Статус» — актуальное состояние относительно целевого ТЗ.

| Тема | Уже есть | Где в коде | Чего ещё нет | Статус |
|---|---|---|---|---|
| Вход | Telegram (без обязательного Google) | `account_auth.py`, `google_auth.py`, `ui.js` | Google OAuth secrets — для привязки перед NT | ✅ login / ✅ NT step-up |
| Права / blur | `free_preview`: news+docs+demo+practice+community | `permissions.py`, `subscriptions.py`, `ui.js` | Полный paid backtest по-прежнему за подпиской | ✅ demo-tier |
| Сессии | Kill, Monitoring tab, journal, admin-kill UX | `account_auth`, `user_support`, `ui.js` | Живой owner UI E2E | ✅ |
| Скрин | С согласием пользователя | `user_support.py`, consent UI | Silent stream запрещён — оставляем | ✅ |
| Телеметрия | CPU/RAM/сеть вкладки браузера | `user_support.record_telemetry` | Не обещать ядра ОС | ✅ (browser) |
| Торговля | Practice + Micro Live + paper | `practice-trading.html`, `micro-live.html`, `trading.html` | Full live NT — отдельно | ✅ practice / ✅ micro / 🟡 full live |
| Графики 1–8 | Desktop + practice 1/2/4 | `desktop.html`, `practice-trading.html` | Practice 6/8 не MVP | ✅ engine / 🟡 practice layouts |
| Topstep | Статус/scaffold | `topstep.html` | Не заменяет practice | 🟡 scaffold |
| Бэктест | Full UI + demo-tier | `backtesting.html`, `demo_backtest.py` | — | ✅ |
| ИИ чат | Orchestrator + owner Telegram mirror | `chief_agent.py`, `telegram_service.py` | Community отдельно | ✅ orch / ✅ community |
| ★★★ | Persist + meta + агрегаты + router | `chief_agent.rate_message`, `ai_ratings.py`, `agent_router.py` | Живая серия 10 задач на prod моделях | ✅ |
| Staging / impersonation | `runtime_env`, `test_auth`, banner | `docs/STAGING_QA.md` | Полный E2E на отдельном data root | ✅ |
| Community страница | `community.html` + API | `community.py` | Нужен `NTA_COMMUNITY_TELEGRAM_CHAT_ID` для live mirror | ✅ |
| Micro Live | `micro_live.py` + UI | capability `micro_live`, staging stubs | Реальные broker fills / payments — prod gate | ✅ MVP / 🟡 prod money |

---

# ЧАСТЬ 2. ПОДРОБНО ПО КАЖДОМУ ПУНКТУ

Ниже для каждого пункта:
1. Что сделать  
2. Где менять  
3. Как правильно реализовать  
4. Что обязательно перепроверить после выполнения  

---

## ПУНКТ 1. Сессии пользователей и мониторинг ресурсов

> **Статус: ✅ ~95% (код+автотесты).** Monitoring tab, `session_admin_revoked`, telemetry note, consent-скрин. Остаток: ручной E2E owner UI на живом сервере (не блокер MVP).

### 1.1. Что нужно сделать
Админ должен уметь:
- видеть список активных пользователей и их сессий;
- принудительно закрыть одну сессию или все сессии пользователя;
- запросить снимок экрана / состояние интерфейса (только с согласием);
- видеть сеть, память, CPU (и по возможности ядра) с разбивкой по пользователям;
- видеть время подключения, статус, активность, устройства;
- видеть журнал своих админ-действий.

### 1.2. Где менять (конкретно)

| Что | Файл | Статус |
|---|---|---|
| Backend сессий | `account_auth.py` | ✅ |
| Backend телеметрии | `user_support.py` | ✅ |
| API routes | `server.py` | ✅ |
| Админ UI | `ui.js` Monitoring + kill UX | ✅ |
| Журнал | `admin_journal.py` | ✅ |
| Тесты | `test_cabinet.py`, `test_account_auth.py`, `test_phase_a_auth.py` | ✅ |

### 1.3. Как правильно реализовать
1. **Не ломать** текущий consent-screenshot. Silent live stream — НЕ делать в MVP.
2. В карточке пользователя и в отдельной вкладке «Мониторинг» показать online sessions, browser telemetry, auth sessions + Завершить.
3. При kill session — сообщение «Сессия завершена администратором».
4. CPU/RAM/сеть: **метрики вкладки браузера**, не ядра ОС.

### 1.4. Обязательно перепроверить
- [x] Owner видит список пользователей и online-сессии.
- [x] «Завершить» / «Завершить все».
- [x] Consent-скрин; отказ и согласие.
- [x] Телеметрия вкладки; journal; не-owner запрещён.
- [x] Admin-kill → `session_admin_revoked` + понятный текст.
- [x] Вкладка «Мониторинг» в кабинете.
- [ ] Ручной E2E на живом owner UI — ⚪ у владельца.

---

## ПУНКТ 2. Демоверсия для новых пользователей (вместо blur)

> **Статус: ✅ ~90% (код+автотесты).** `demo_backtest` capability, 1-click сценарии, watermark, quota 3/день. Остаток: ручной UI E2E free user — ⚪ у владельца.

### 2.1. Что нужно сделать
Новый пользователь после регистрации должен:
- видеть не «всё замылено», а рабочие демо-разделы;
- выбрать готовую демо-стратегию;
- одним кликом запустить демо-бэктест;
- увидеть сделки, графики, PnL, просадку, комиссии, отчёт;
- понимать, что данные **нереальные** (watermark);
- видеть кнопку «что откроется после подписки».

### 2.2. Где менять

| Что | Файл | Статус |
|---|---|---|
| План free_preview | `subscriptions.py` | ✅ demo_backtest + limits |
| Права / nav | `permissions.py` | ✅ |
| UI / watermark / CTA | `backtesting.js`, `ui.js` | ✅ |
| Backend | `demo_backtest.py` + routes | ✅ |
| Тесты | `test_demo_backtest.py` | ✅ |

### 2.3. Как правильно реализовать
1. Режим demo-tier на `free_preview` (не полный backtesting).
2. 1-click demo backtest без NT; watermark; CTA upgrade; дневной лимит.
3. Live/real money недоступны.

### 2.4. Обязательно перепроверить
- [x] Free-user запускает демо-бэктест без подписки.
- [x] Результат/сделки/метрики читаемы.
- [x] Watermark + CTA.
- [x] Live/real money недоступны.
- [x] Лимит демо/день.
- [x] pytest demo/permissions.
- [ ] Ручной Telegram → демо → отчёт — ⚪ у владельца.

---

## ПУНКТ 3. Страница учебной торговли (как Topstep, виртуальные деньги)

> **Статус: 🟡 UX-fix (16.07.2026).** Backend MVP был ✅; владелец зафиксировал критический UX: **нельзя** сразу показывать MNQ/Buy/ticket. Сначала только вопрос о сумме виртуального депозита; после создания счёта — полноценный торговый экран по логике TopStep (графики, котировки, инструменты, ордера, позиции, PnL, риск, отчёты), деньги полностью виртуальные.

### 3.0. Замечание владельца (зафиксировано 16.07.2026)
1. При открытии «Учебная торговля» **не** показывать форму ордера / MNQ / Buy как будто сделка уже начата.
2. Первый шаг — **только**: «какую сумму виртуальных денег внести на учебный счёт».
3. После ввода суммы и создания счёта открывается торговый терминал **один в один по логике и удобству как в TopStep**.
4. Единственная разница с реалом: баланс, сделки и PnL — виртуальные (не live / не Micro Live / не NT ledger).

### 3.1–3.3. Требования
Отдельная учебная страница: виртуальный депозит → затем market/limit/SL/TP, позиции/отчёты, бейдж «не реальные деньги». Не смешивать с live NT (`trading.html`) и Topstep status scaffold.

Реализовано: `practice_trading.py`, NAV «Учебная», API `/api/practice/*`, `tests/test_practice_trading.py`.  
**UX 16.07:** `practice-onboard` (сумма) → `practice-desk` (ChartEngine + ticket + риск + отчёт); beginner может читать `/api/ops/runtime/bars*` только для графиков.

### 3.4. Обязательно перепроверить
- [x] Учебный счёт / market / limit / SL-TP / daily-loss lock / отчёты.
- [x] Нет записи в live NT.
- [x] pytest practice.
- [x] Без счёта виден **только** экран выбора суммы (нет ticket/MNQ).
- [x] После депозита открывается терминал (KPI / график / ticket / позиции / риск / отчёт).
- [ ] Phone viewport + полный ручной сценарий с живыми котировками NT — ⚪ у владельца.

---

## ПУНКТ 4. Страница сообщества пользователей

> **Статус: ✅ ~80% (код+автотесты).** `community.py`, страница, chat/publish/copy/ratings/moderation. Telegram duplicate через `NTA_COMMUNITY_TELEGRAM_CHAT_ID` (отдельно от Orchestrator). Live mirror — ⚪ без chat_id.

### 4.1–4.2. Правило
Два контура: Owner/AI Orchestrator ✅ и Community ✅ — не смешивать. Community **не** пишет в owner topics.

### 4.3. Реализовано
`community.html` / `community.js`, `/api/community/*`, `mirror_community_message`, `tests/test_community.py`.

### 4.4–4.5. Перепроверить
- [x] Community страница / сообщения не в Orchestrator.
- [x] Publish / copy / ratings / block.
- [x] Telegram community ≠ owner mirror.
- [x] pytest community.
- [ ] `NTA_COMMUNITY_TELEGRAM_CHAT_ID` + ручной mobile — ⚪ у владельца.

---

## ПУНКТ 5. Google + Telegram step-up для NinjaTrader (не для входа)

> **Статус: ✅ ~95% (продуктовая модель уточнена 15.07.2026).** Вход — только Telegram, как раньше. Весь кабинет (демо, учебная, community, AI, новости…) доступен без Google. Google OAuth + повторное подтверждение в Telegram обязательны **только** перед действиями управления NinjaTrader (личный bridge / команды в NT / live). Наблюдение за контуром владельца — без Google.

### 5.1. Что нужно сделать
- Вход в приложение: **только Telegram** (без обязательного Google).
- Перед подключением своего NT или выполнением команд в NinjaTrader (в т.ч. на Pro/developer):  
  1) привязать Google;  
  2) повторно подтвердить действие кнопкой в Telegram (step-up ~30 мин).
- Один Google ↔ один профиль; devices / revoke / audit сохраняются.
- Без Google пользователь не «ломается» — просто не может управлять NT.

### 5.2. Где менять

| Что | Файл | Статус |
|---|---|---|
| Политика NT gate | `account_auth.nt_action_gate` / `require_nt_dual_auth` | ✅ + hardening: raw user по `user_id` |
| Google OAuth | `google_auth.py` + routes | ✅ |
| Telegram step-up | `start_nt_telegram_confirm` + callback `nt_confirm:` | ✅ |
| API middleware | `server.py` `path_requires_nt_dual_auth` | ✅ |
| UI | кабинет «Мой NinjaTrader» + `ensureNtDualAuth` | ✅ |
| Тесты | `tests/test_nt_dual_auth.py`, `test_workspaces.py` | ✅ pair + forged flag |

### 5.3. Как правильно реализовать
1. Telegram login → полный доступ к не-NT разделам.
2. Пользователь нажимает «Подключить свой NinjaTrader» / pair / paper|live command.
3. Если нет Google → экран привязки Google (не блокирует остальной UI).
4. Если Google есть, но нет свежего Telegram confirm → сообщение в бот с ✅/⛔.
5. После confirm сессия получает `nt_elevated_until` (~30 мин).
6. Owner освобождён от step-up (свой NT).

### 5.4. Обязательно перепроверить
- [x] Новый user без Google входит и пользуется demo/practice/community.
- [x] Без Google нельзя создать personal workspace / bridge pair / NT command.
- [x] Один Google нельзя привязать к двум профилям.
- [x] После Google нужен Telegram confirm перед NT.
- [x] Наблюдение owner-runtime не требует Google.
- [x] Revoke session / device list работают.
- [x] Production secrets не в git.
- [x] pytest `test_nt_dual_auth` + `test_workspaces` (в т.ч. forged `google_linked`).
- [x] `require_nt_dual_auth` проверяет raw `google_sub` в store по `user_id`.
- [ ] Ручной OAuth прогон на staging с реальным Google client — ⚪ секреты владельца.

---

## ПУНКТ 6. Режим проверки «глазами пользователя» (самый важный для владельца)

> **Статус: ✅ ~90% (код+автотесты).** `runtime_env`, `test_auth.py`, impersonation + red banner, prod lock, `docs/STAGING_QA.md`. Полный ручной E2E на отдельном data root — ⚪ у владельца.

### 6.1–6.3. Реализовано
Staging isolation gates, virtual users, fake Google link, «Войти как» + banner + return, presets, audit, запрет payments/live в staging по умолчанию.

### 6.4. Обязательно перепроверить
- [x] Test auth / impersonation blocked in production (startup assert).
- [x] Banner + return to admin.
- [x] Presets / staging Telegram mirror gated.
- [x] pytest phase_a / staging.
- [ ] Полный ручной E2E desktop+phone на отдельном data root — ⚪ у владельца.

---

## ПУНКТ 7. Micro Live / Scaled Live (реальные деньги в уменьшенном масштабе)

> **Статус: ✅ ~85% (MVP).** `app/micro_live.py`, capability `micro_live`, nav + `micro-live.html`, free 5 trades, scale 1:100, PnL comparison, warning gate, staging stubs. Не путать с именами стратегий вроде `NTAMicroMnqScalpPilot`.

### 7.1. Что нужно сделать
1. После регистрации дать **3–5 бесплатных сделок** без денег пользователя.
2. Потом режим реальной торговли с масштабом (например 1:100):  
   маржа «как $100 на бирже», у пользователя фактически ~$1.
3. Показывать реальный PnL и эквивалент на полном объёме:  
   «Вы заработали $0.85 ≈ $85 на полном объёме при 1:100».
4. Пользователь должен чувствовать, что деньги реальные, но риск маленький.

### 7.2. Где менять

| Что | Файл / место | Действие |
|---|---|---|
| Новый режим счёта | `app/micro_live.py` (+ ledger) | ✅ Отдельно от practice/paper |
| UI | `micro-live.html` + `assets/pages/micro-live.js` | ✅ Бейджи «Реальные деньги · масштаб 1:N» |
| Права | `permissions.py`, `subscriptions.py` | ✅ Capability `micro_live` (не на free_preview) |
| Платежи/депозит | `micro_live.deposit` + runtime_env gates | ✅ Staging stub; prod требует `allow_real_payments` |
| Runtime safety | `server.py`, `runtime_env.allow_live_orders` | ✅ Staging simulated fills |
| Тесты | `tests/test_phase_d.py` | ✅ |

### 7.3. Как правильно реализовать
1. Жёстко разделить три режима в UI и backend:
   - **Demo** = тестовые данные;
   - **Practice** = виртуальные деньги;
   - **Micro Live** = реальные деньги × scale.
2. Free 3–5 trades: счётчик на пользователя, без списания денег.
3. MVP scale: один коэффициент (например 1:100), не все сразу.
4. Risk guards: max daily loss, max notional, circuit breaker.
5. Staging: только симуляция платежей/fills. Реальные деньги — только Production после явного включения владельцем.

### 7.4. Обязательно перепроверить
- [x] Free trades не списывают деньги и уменьшают счётчик.
- [x] После лимита включается Micro Live (или CTA на депозит).
- [x] Масштаб корректно считает маржу/PnL/эквивалент полного объёма.
- [x] Бейджи не путают с paper/demo.
- [x] Risk lock срабатывает. *(daily_loss при отрицательном балансе сверх лимита)*
- [x] Staging не проводит реальные платежи.
- [x] Ledger и отчёты сходятся. *(ledger deposits + trades list)*
- [x] Юридические/риск-предупреждения показаны до первой реальной сделки.

*(MVP принят по автотестам + scripted checklist. Prod broker fills — отдельный шаг после включения gates.)*

---

## ПУНКТ 8. Рейтинги ИИ: должности / модели / связка (на базе ★★★)

> **Статус: ✅ ~90%.** `ai_ratings.py` + запись из `rate_message` + re-rank в `agent_router.candidates()` + owner UI «Рейтинги ИИ». Gates ключей/бюджета/cooldown не обходятся.

### 8.1. Что нужно сделать
У нас уже есть три звезды под каждым ответом. Нужно:
1. В конце ответа показывать: **должность**, **модель**, **оценка**.
2. Сохранять оценки в 3 рейтинга:
   - рейтинг должностей;
   - рейтинг моделей;
   - рейтинг связки «должность + модель» (главный).
3. По главному рейтингу чаще назначать лучшие связки, но иногда давать задачи другим моделям (exploration), чтобы не застрять на одной.

### 8.2. Где менять

| Что | Файл | Сейчас | Нужно |
|---|---|---|---|
| Оценка сообщения | `chief_agent.rate_message` | ★ + агрегаты ✅ | — |
| UI звёзд | `ui.js` orch-rating + meta | ★ + meta ✅ | — |
| API рейтингов | `GET /api/ai-lab/ratings` | Owner tables ✅ | — |
| Router | `agent_router.candidates` | rating + exploration после gates ✅ | — |
| Админ UI | кабинет вкладка «Рейтинги ИИ» | ✅ | — |
| Тесты | `tests/test_phase_d.py` | ✅ order + key gate | — |

### 8.3. Как правильно реализовать
1. При каждом assistant-ответе сохранять метаданные: `role_id`, `model_id`, `provider`, `task_category`.
2. При ★ обновлять агрегаты:
   - `role_stats`
   - `model_stats`
   - `role_model_stats`
3. Формула MVP простая:
   - скользящее среднее ★;
   - штраф за 1★ и failed fulfillment;
   - decay по времени;
   - exploration 5–15% задач на альтернативы.
4. Feature-flag: сначала «рекомендация/отчёт», потом авто-routing.
5. Не переходить сразу на 5★ — не ломать текущий UX 3★.

### 8.4. Обязательно перепроверить
- [x] Под ответом видны должность, модель, звёзды. *(meta + ★ есть; можно свести в один блок)*
- [x] Оценка 1/2/3 сохраняется и переживает reload.
- [x] Админ видит 3 таблицы рейтингов.
- [x] После серии высоких ★ связка начинает выбираться чаще. *(unit: rank_agents)*
- [x] Exploration всё ещё иногда выбирает другую модель. *(EXPLORATION_RATE=0.10)*
- [x] Auto-penalty failed не ломает owner-оценки. *(auto-penalty в chief_agent есть)*
- [x] Router без ключей/бюджета по-прежнему безопасен (не обходит gates).
- [x] pytest + scripted ranking checklist. *(живая серия 10 задач на внешних моделях — у владельца на staging)*

---

## ПУНКТ 9. Режимы «Новичок» и «Профессионал» (определяют весь продукт)

> **Статус: ✅ MVP (Фаза E).** Реализация по §9.0 / чеклист 9.4. Ручной staging E2E / mobile viewport — у владельца.

### 9.0. Ответы владельца (зафиксировано)

1. **Новичок НЕ видит** Community / новости / документы. Только: кошелёк → инструмент → график → сделки → простой отчёт.
2. **Новичок→Профессионал** — самостоятельно, с коротким предупреждением. **Профессионал→Новичок** — только с явным подтверждением (стратегии/ИИ/NT скроются).
3. **Owner всегда Профессионал** (на staging impersonation может смотреть beginner-пресет).
4. Сначала коммит объёма A–D (по фазам) + pytest; Фаза E — только по отдельной команде после аудита коммитов.

### 9.1. Что нужно сделать
При первом входе (и с возможностью смены позже с предупреждением) пользователь выбирает один из двух режимов. **Весь функционал приложения зависит от выбора.**

#### Режим «Новичок» (простой трейдер)
Цель: познакомить с обычным торговым интерфейсом, как у популярных демо-счетов. Максимально просто.

Доступно:
1. Внести виртуальные деньги → увидеть баланс на «кошельке».
2. Выбрать инструмент → открыть график(и).
3. Торговать (market/limit, базовый ticket) → видеть изменение баланса / PnL.
4. Простые отчёты по сделкам.

Всё взаимодействие — **как на демо-счёте**: цены рыночные/корректные, но доходы/расходы/баланс виртуальные.  
Часть функционала **скрыта / отсутствует**:
- разработка и портфель стратегий;
- AI Lab / Orchestrator / агенты разработки стратегий;
- полный backtesting research;
- Micro Live / Full Live / подключение своего NinjaTrader (или только после явного апгрейда режима);
- сложные разделы владельца.

Nav новичка: короткое меню (кошелёк / торговля / график / отчёт), без «профессионального шума».

#### Режим «Профессионал»
Цель: полный контур как у опытного разработчика/трейдера стратегий.

Доступно (по тарифу/правам):
- стратегии, правила разработки с ботами, бэктест, AI Lab / агенты;
- Desktop charts, paper/live (с Google+Telegram step-up для NT);
- Community, документы, новости;
- Micro Live и расширенные режимы денег;
- кабинет/подписки как сейчас для paid/pro.

### 9.2. Где менять

| Что | Файл / место | Действие |
|---|---|---|
| Поле профиля | `account_auth` user doc | `ux_mode`: `beginner` \| `professional` |
| Онбординг UI | `ui.js` / login после Telegram | Экран выбора 2 карточек |
| Permissions / nav | `permissions.py`, `ui.js` NAV | Разные nav + capabilities presets по режиму |
| Торговый UX новичка | переиспользовать `practice_trading` + упрощённый layout | Кошелёк → инструмент → график → ticket |
| Скрытие разделов | nav lock + API soft-deny | Стратегии/AI недоступны в beginner |
| Смена режима | кабинет профиля | С предупреждением; beginner→pro открывает разделы |
| Staging presets | `test_auth` | presets `beginner` / `professional` |
| Тесты | `tests/test_ux_mode.py` | Nav, API deny, wallet flow |

### 9.3. Как правильно реализовать
1. После Telegram-логина, если `ux_mode` пуст → экран выбора (нельзя «пропустить» без выбора).
2. Beginner по умолчанию мапит на practice/demo контур; **не** путать с Micro Live.
3. Professional сохраняет текущую матрицу тарифов (`free_preview` / paid / founder).
4. Смена beginner→professional — разрешена; professional→beginner — с подтверждением (скрыть стратегии/ИИ).
5. Не ломать owner: владелец всегда в professional (или видит оба через impersonation).

### 9.4. Обязательно перепроверить
- [x] После входа без режима — только экран выбора.
- [x] Новичок: кошелёк → инструмент → график → сделка → баланс меняется. *(practice contour + тесты)*
- [x] Новичок: в nav **нет** Стратегии / AI Lab / Community / новости / документы / Micro Live / NT connect.
- [x] Профессионал: полный nav по тарифу как сейчас.
- [x] API beginner не отдаёт strategy/AI/community write даже при прямом URL.
- [x] Демо-суммы не пишутся в live/micro ledger. *(practice store изолирован)*
- [x] Смена режимов по правилам §9.0.
- [x] Owner всегда professional.
- [x] Staging preset beginner / professional.
- [x] pytest `test_ux_mode.py` + ручной mobile viewport. *(CSS `@media (max-width: 720px)` + контракт; визуал — у владельца)*

---

# ЧАСТЬ 3. КАК ПРАВИЛЬНО СТРОИТЬ РАБОТУ РАЗРАБОТЧИКАМ

## Правило 1. Не начинать с community и Micro Live
Сначала A (staging/auth/impersonation/sessions), потом B (demo + practice), потом C/D, затем **E (режимы Новичок/Профессионал)** как сквозная перестройка UX.

## Правило 2. Каждый пункт = код + тесты + ручной чеклист
Нельзя считать задачу сделанной, если нет:
- unit/API тестов;
- ручной проверки по чеклисту пункта;
- проверки, что старое не сломано (Telegram login, Orchestrator mirror, free_preview grants, paper trading).

## Правило 3. Не смешивать режимы денег **и** режимы пользователя
Всегда разные бейджи и разные backend контуры денег:
- Demo
- Practice (virtual)
- Micro Live (real × scale)
- Full live (если вообще будет)

И отдельно — режим UX:
- **Новичок** = только простой демо-трейдинг
- **Профессионал** = стратегии / ИИ / NT / расширенные разделы

## Правило 4. Не смешивать чаты
- Orchestrator/AI = владелец + агенты
- Community = пользователи между собой
- Telegram sync для community = отдельный канал

## Правило 5. Staging safety
Перед любым merge проверять:
- test auth выключен в prod;
- нет записи staging → prod DB;
- нет реальных платежей/live orders из test mode.

---

# ЧАСТЬ 4. ЧЕКЛИСТ ПРИЁМКИ ВСЕГО ПРОЕКТА

Владелец принимает работу только если выполнено всё ниже.

> **Повторный аудит 16.07.2026:** реализация и автоматические ворота фаз A–E завершены. Финальная production-приёмка остаётся заблокирована только обязательными внешними credentials/адаптерами и ручной визуальной/Strategy Analyzer матрицей.

## Фаза A
- [x] Dual-auth для NinjaTrader: Google + Telegram step-up ✅ *(вход — только Telegram; Google не обязателен для остальных разделов)*
- [x] Список без Google / admin migration API ✅ *(информативно для NT, не login-block)*
- [x] Staging + virtual user + «войти как» + banner ✅
- [x] Session kill + telemetry + consent screenshot + journal ✅ *(+ Monitoring tab + `session_admin_revoked`)*

## Фаза B
- [x] Demo вместо blur: 1-click backtest + watermark + CTA ✅ *(автотесты; ручной UI — у владельца)*
- [x] Учебная торговля MVP 1/2/4 + virtual account + отчёты ✅ *(автотесты; 6/8 charts не в MVP)*
- [x] **Wallet-first UX учебной торговли** ✅ *(16.07: сначала только сумма депозита → затем TopStep-like desk; ручной live-quotes E2E — у владельца)*

## Фаза C
- [x] Community page + chat + publish/copy + simple ratings ✅
- [x] Отдельный Telegram duplicate community ✅ *(через `NTA_COMMUNITY_TELEGRAM_CHAT_ID`; на staging по умолчанию выкл.)*
- [x] Orchestrator mirror не сломан ✅

## Фаза D
- [x] Free 3–5 trades → Micro Live scale + PnL comparison ✅ *(MVP; staging stubs; prod broker — gate)*
- [x] AI ★ → 3 рейтинга → routing с exploration ✅

## Фаза E (новый блок)
- [x] Выбор режима Новичок / Профессионал при онбординге ✅
- [x] Beginner UX: кошелёк → инструмент → график → сделки (всё виртуально) ✅ *(practice + watermark + redirect)*
- [x] Beginner: скрыты стратегии / AI Lab / NT connect / Micro Live ✅
- [x] Professional: текущий полный контур по тарифу ✅
- [x] Смена режима + staging presets + тесты ✅

**Фазы A–E:** код/API/автотесты ✅. Production release: **BLOCKED** до выполнения внешней и ручной матрицы ниже.

**Блокеры владельца (без остановки остальной работы):**
1. Staging Google OAuth client id/secret и allowed redirect URI — для реальной привязки перед управлением NinjaTrader.
2. Staging Telegram bot, owner chat и отдельный `NTA_COMMUNITY_TELEGRAM_CHAT_ID`.
3. Явно разрешённый ручной UI E2E в двух браузерных профилях и mobile viewports (`NTA_APP_ENV=staging`, `NTA_ENABLE_TEST_AUTH=1`).
4. NinjaTrader Strategy Analyzer для ручного сравнения bridge/backtest-контракта.
5. Одобренные payment-provider и broker sandbox adapters; реальные деньги/orders требуют отдельного письменного разрешения и лимитов.

---

# ЧАСТЬ 5. ВОРОНКА ПОЛЬЗОВАТЕЛЯ (как должно работать в итоге)

```
1. Вход: Telegram (без обязательного Google)
2. Выбор режима: Новичок ИЛИ Профессионал
3a. Новичок: виртуальный кошелёк → инструмент → график → сделки → баланс
3b. Профессионал:
    - онбординг / демо / учебная / community по тарифу
    - стратегии + ИИ-боты
    - перед NT: Google + Telegram confirm
    - Micro Live / подписка
```

Параллельно для владельца:
```
Staging → Virtual user → Войти как пользователь → пройти тот же путь
Админка сессий/ресурсов
Оценки ★ → рейтинги ИИ → умное назначение моделей
```

---

# ЧАСТЬ 6. ЧТО ОБЯЗАТЕЛЬНО ПЕРЕПРОВЕРИТЬ ПЕРЕД СДАЧЕЙ (ОБЩЕЕ)

Разработчик перед сдачей каждого пункта обязан:

1. Прогнать релевантные `pytest` в `NT-Analyzer/tests/`.
2. Проверить ручной сценарий пункта по чеклисту выше.
3. Проверить регрессии:
   - вход через Telegram;
   - кабинет владельца / users;
   - Orchestrator чат и ★;
   - Telegram mirror владельца;
   - backtesting для owner;
   - desktop charts;
   - permissions/promo/voucher.
4. Убедиться, что новые секреты не в git.
5. Убедиться, что demo/practice/micro-live визуально и в API не перепутаны.
6. Зафиксировать в PR/отчёте: что сделано, какие файлы, какие тесты, какие ручные проверки.

---

# ЧАСТЬ 7. ИТОГ ОДНИМ АБЗАЦЕМ

Нужно доработать StratForge так, чтобы: владелец управлял сессиями и мог сам пройти весь путь пользователя на staging; вход был через Telegram; после входа пользователь выбирал режим **Новичок** (простой демо-трейдинг: кошелёк → график → сделки) или **Профессионал** (стратегии, ИИ, NT, расширенные разделы); перед управлением NinjaTrader требовались Google и повторное Telegram-подтверждение; community, Micro Live и рейтинги ИИ работали в pro-контуре. Каждый пункт после реализации обязан быть покрыт тестами и ручной проверкой по чеклистам этого файла.

---

## СТАТУС ПОСЛЕ ПОВТОРНОГО АУДИТА ФАЗ A–E (16.07.2026)

Фазы A–E завершены в коде и автоматической проверке. Work 5: политика NT-only подтверждена владельцем.
**Фаза E / Пункт 9: режимы Новичок и Профессионал реализованы** (`ux_mode`, gate UI, permissions/API deny, presets, `tests/test_ux_mode.py`).

Повторный независимый прогон: **618 pytest passed**, **13/13 legacy suites**, Python compile, **32/32 JavaScript syntax**, CSP/secrets/Markdown scan и NinjaTrader bridge build (**0 warnings / 0 errors**) — PASS. Staging soak: **2133/2133 HTTP 200**, 0 ошибок/5xx/SQLite locks, 10 виртуальных пользователей, production guard неизменён. Интерактивный Orchestrator/domain AI и тяжёлые chart batches переведены в durable worker; idempotency, cancel/retry/lease и реальный process-crash supervisor probe — PASS. Окончательный локальный production backend перезапущен: UI/resources HTTP 200, worker жив, stderr пуст; read-only Telegram bot/webhook/owner-chat probe — PASS.

Остаточные блокеры production-приёмки: реальные Google/Telegram credentials; payment/broker sandbox adapters и отдельное разрешение на money/order tests; ручной staging E2E/visual mobile/двухпрофильная сессия; NinjaTrader Strategy Analyzer. Это внешние проверки, а не незакрытая кодовая задача.

---

*Конец документа. Это единственный главный файл-задание для разработчиков. Статус и приёмочные пометки повторно сверены с кодом и автоматическими воротами 16.07.2026; полный release-аудит: `NT-Analyzer/docs/STRATFORGE_RELEASE_AUDIT_2026-07-15.md`.*
