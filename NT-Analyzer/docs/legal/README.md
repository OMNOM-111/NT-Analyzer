# Юридический пакет StratForge AI (пользовательские документы)

**Статус пакета:** документ 1 реализован как единое соглашение регистрации
`2026-08-30-v2`; документы 2-9 остаются research-шаблонами `v0.1-DRAFT` и не
публикуются как действующие условия. Лицензированный юрист в применимой
юрисдикции всё ещё должен проверить финансовые/CFTC-NFA вопросы,
privacy/data-flow и любое автоматическое торговое исполнение до юридического
closeout продукта.

**Дата подготовки проекта:** 2026-08-10<br>
**Продукт:** StratForge AI (репозиторий/технический идентификатор — `NT-Analyzer`)<br>
**Метод:** тексты подготовлены на основе двух research-документов владельца
(первый — как основной master-source, второй — как дополнительный research-source
для проверки полноты и устранения пробелов, без механического слияния) и
подтверждены по фактической реализации (код и документация репозитория на
2026-08-10). Ничего не выдумано: формулировки о данных опираются на проверенный
data-flow (см. таблицу ниже).

> Документы 2-9 — глубоко проработанные черновые шаблоны, а не юридическое
> заключение адвоката, допущенного к практике в конкретной стране или штате.
> Реализация документа 1 в продукте не заменяет независимую юридическую проверку.

## Состав пакета

| № | Файл | Назначение |
|---|---|---|
| 1 | [00_KEY_LEGAL_POINTS.md](00_KEY_LEGAL_POINTS.md) | Единое пользовательское соглашение версии `2026-08-30-v2` для онбординга |
| 2 | [01_TERMS_OF_SERVICE_EULA.md](01_TERMS_OF_SERVICE_EULA.md) | Расширенный research/EULA-шаблон для counsel-review |
| 3 | [02_PRIVACY_POLICY.md](02_PRIVACY_POLICY.md) | Политика конфиденциальности (по подтверждённому data-flow) |
| 4 | [03_TRADING_AUTOMATION_RISK_DISCLOSURE.md](03_TRADING_AUTOMATION_RISK_DISCLOSURE.md) | Раскрытие торговых и автоматизационных рисков |
| 5 | [04_THIRD_PARTY_INTEGRATIONS_AND_MARKET_DATA.md](04_THIRD_PARTY_INTEGRATIONS_AND_MARKET_DATA.md) | Сторонние интеграции и market data (NinjaTrader, TopstepX, Telegram, Databento, Yahoo, AI, Google) |
| 6 | [05_AI_DISCLOSURE_AND_DATA_PROCESSING.md](05_AI_DISCLOSURE_AND_DATA_PROCESSING.md) | AI Disclosure и AI Data Processing Notice |
| 7 | [06_AUTOMATION_LIVE_TRADING_ACTIVATION_CONSENT.md](06_AUTOMATION_LIVE_TRADING_ACTIVATION_CONSENT.md) | Отдельное согласие на автоматизацию / live-торговлю |
| 8 | [07_CONSENT_AND_ELECTRONIC_ACCEPTANCE_POLICY.md](07_CONSENT_AND_ELECTRONIC_ACCEPTANCE_POLICY.md) | Политика и UX электронного акцепта, versioned evidence, re-consent, withdrawal |
| 9 | [08_COOKIE_ANALYTICS_AND_REGIONAL_ADDENDA.md](08_COOKIE_ANALYTICS_AND_REGIONAL_ADDENDA.md) | Cookie/Analytics Notice + California и EU/EEA addenda |

На онбординге пользователь подписывает **только документ 1**. Он является
самодостаточным: обязательства пользователя не зависят от текста остальных
восьми файлов. Остальные файлы — research-материалы и шаблоны для counsel-review;
они не включаются в договор по скрытой ссылке и не создают отдельного клика.

Каждый документ самостоятелен: его можно открыть, сохранить и распечатать
отдельно. Приложение должно ссылаться на **конкретную версию** (`version` +
`effective_date` в шапке), а не на «последний текст на сайте».

## Единые placeholders (ТРЕБУЮТ РЕШЕНИЯ ВЛАДЕЛЬЦА)

Перед публикацией заменить во всех документах. До замены — не публиковать.

- `[ТРЕБУЕТ РЕШЕНИЯ ВЛАДЕЛЬЦА — OPERATOR_LEGAL_NAME]` — точное юридическое лицо/ИП оператора
- `[ТРЕБУЕТ РЕШЕНИЯ ВЛАДЕЛЬЦА — ENTITY_TYPE]` — LLC / Corporation / Individual / иное
- `[ТРЕБУЕТ РЕШЕНИЯ ВЛАДЕЛЬЦА — REGISTERED_ADDRESS]` — юридический адрес
- `[ТРЕБУЕТ РЕШЕНИЯ ВЛАДЕЛЬЦА — GOVERNING_STATE]` / `[… — COUNTY]` — применимый штат/округ США
- `[ТРЕБУЕТ РЕШЕНИЯ ВЛАДЕЛЬЦА — SUPPORT_EMAIL / PRIVACY_EMAIL / SECURITY_EMAIL / LEGAL_EMAIL / ARBITRATION_OPTOUT_EMAIL]`
- `[ТРЕБУЕТ РЕШЕНИЯ ВЛАДЕЛЬЦА — WEBSITE]` / `[… — PRIVACY_POLICY_URL]`
- `[ТРЕБУЕТ РЕШЕНИЯ ВЛАДЕЛЬЦА — EFFECTIVE_DATE]` / `[… — VERSION]`
- `[ТРЕБУЕТ РЕШЕНИЯ ВЛАДЕЛЬЦА — ARBITRATION_PROVIDER]` — AAA / JAMS / иное
- `[ТРЕБУЕТ РЕШЕНИЯ ВЛАДЕЛЬЦА — LIABILITY_CAP]` — денежный предел ответственности
- `[ТРЕБУЕТ РЕШЕНИЯ ВЛАДЕЛЬЦА — RETENTION_*]` — конкретные сроки хранения
- `[ТРЕБУЕТ РЕШЕНИЯ ВЛАДЕЛЬЦА — MONETIZATION_MODEL / REFUND_MODEL]` — модель оплаты/возвратов

## Соответствие: SOURCE REQUIREMENT → ACTUAL PRODUCT STATE → LEGAL DOCUMENT/SECTION → STATUS

Таблица доказывает, что документы соответствуют приложению. «Actual product
state» подтверждён по коду (см. inventory на 2026-08-10).

| Source requirement (из research) | Actual product state (по коду) | Legal document / section | Status |
|---|---|---|---|
| Заметный clickwrap, непредустановленная галочка, versioned assent | Требует реализации в onboarding UI; backend хранит consent-записи в `accounts.dpapi` | Doc 8 §UX + §Evidence; Doc 2 §Принятие | СПЕЦИФИКАЦИЯ ГОТОВА; UI требует внедрения |
| Не обещать абсолютную безопасность | В коде — DPAPI, scrubbed logs, least privilege; абсолютной гарантии нет | Doc 2 §Безопасность; Doc 3 §Cyber; Privacy §Security | СООТВЕТСТВУЕТ |
| Local-first честно | DPAPI-локальные store; Dev=127.0.0.1; Production=PostgreSQL | Privacy §Local/Server; Doc 2 §Local-first | СООТВЕТСТВУЕТ |
| Отделить market/user/software/connectivity/third-party/AI/automation риски | Practice virtual; paper w/ step-up; live заблокирован; провайдерная цепочка | Doc 3 полностью | СООТВЕТСТВУЕТ |
| Не превращать регулируемую деятельность в «not financial advice» | Аналитика/бэктест/симуляция; персональных рекомендаций/исполнения нет | Doc 2 §9–10; Doc 3 §Regulatory; Doc 1 | СООТВЕТСТВУЕТ; требует counsel-review перед persona-signal/execution |
| Отдельные consent для AI/marketing/Telegram/automation | Cloud AI opt-in + budgets; Telegram permission flow; automation отдельно | Doc 5, Doc 6, Doc 8 | СПЕЦИФИКАЦИЯ ГОТОВА |
| Telegram — минимально необходимые permissions | initData + requestContact (пользователь сам делится телефоном) | Doc 4 §Telegram; Privacy §Telegram | СООТВЕТСТВУЕТ |
| TopstepX read-only, без routing | `read_only=True`, `trade_routing=False`, opt-in | Doc 4 §TopstepX | СООТВЕТСТВУЕТ |
| Нет реального исполнения real-money | `live_commands` → 403 без `NTA_ALLOW_LIVE_ORDERS=1`; режим Sim/Live следует подключённому аккаунту | Doc 3 §Live; Doc 6 §Статус; Doc 2 §Trading | СООТВЕТСТВУЕТ (live = `EXTERNAL BLOCKED`, implementation gap — не будущая стадия) |
| Google/e-mail как методы входа/связывания, а не только step-up | `LOGIN_PROVIDERS=("telegram","google","email")`; /api/auth/google/login/start, /api/auth/email/start, email link | Doc 1 §13; Doc 2 §3/§8; Doc 4 §5 | СООТВЕТСТВУЕТ |
| Платежи честно | `PAYMENTS_ENABLED=False`; ручной PayPal.me; карты в приложении не хранятся | Doc 2 §Оплата; Privacy §Payment | СООТВЕТСТВУЕТ |
| AI: что уходит провайдеру | model+prompt+system+max_tokens; НЕ credentials/account#/keys; usage=hash | Doc 5 §Передача провайдеру | СООТВЕТСТВУЕТ |
| Screenshots — consent + удаление | owner-only, canvas, DPAPI, 24h auto-delete | Privacy §Diagnostics; Doc 2 §Support | СООТВЕТСТВУЕТ |
| Сохранение неотчуждаемых прав | Mandatory-law savings + carve-outs (fraud, EFAA, public injunctive) | Doc 2 §48/§63/§74/§75; Privacy §Rights | СООТВЕТСТВУЕТ |
| 18+ | Возрастная планка задаётся политикой (UI age-gate требует внедрения) | Doc 2 §Возраст; Privacy §Children | ПОЛИТИКА ГОТОВА; UI age-gate требует внедрения |

## REQUIRES OWNER DECISION — короткий список вопросов до публикации

1. Точное юридическое лицо оператора, тип, страна/штат регистрации и адрес.
2. Governing state/county США, арбитраж (провайдер, opt-out) — включать ли арбитраж.
3. Классификация финансовых функций у CFTC/NFA (и, если появятся securities-функции, SEC/IAA) — до включения персональных рекомендаций/исполнения.
4. Модель монетизации и возвратов (сейчас `PAYMENTS_ENABLED=False`, ручной PayPal.me) и раскрытие цен/renewal/cancel.
5. Реальные сроки хранения по каждой категории (retention schedule).
6. Контактные адреса (support/privacy/security/legal/arbitration opt-out) и сайт/URL Privacy Policy.
7. Денежный предел ответственности (`LIABILITY_CAP`) с учётом цены продукта, юрисдикции и страхования.
8. Подтвердить точный юридический субъект интеграции «Unity Trader», если она будет включена (в текущем коде не активна).
9. Подтвердить, используются ли web-analytics/cookies и сторонние SDK (сейчас в коде не обнаружены) — влияет на Doc 8.
10. Решение по возрастной планке (рекомендовано 18+) и age-gate в UI.
11. Требуется ли международная доступность (EEA/California) на старте — влияет на addenda (Doc 8), SCC и CCPA-контролы.
12. Внутренние документы (contractor IP-assignment/NDA/DPA, Incident Response Plan, страхование) — вне пользовательского пакета, но обязательны до релиза.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-10T20:49:49Z | GitHub Copilot (Claude Opus 4.8) через VS Code по запросу owner | Создан пользовательский юридический пакет-проект из 9 документов; статус DRAFT, требуется counsel review.
2026-08-11T08:13:16Z | GPT-5.5 через Codex по запросу owner | Убрана служебная атрибуция из пользовательского тела и актуализирована фактическая market-data схема без изменения статуса DRAFT.
2026-08-30T15:15:14Z | GPT-5.5 через Codex по запросу owner | Документ 1 закреплён как единственное самодостаточное соглашение регистрации версии 2026-08-30-v1; остальные материалы оставлены отдельными research-шаблонами для counsel-review.
2026-08-30T20:17:36Z | GPT-5.5 через Codex по запросу owner | Соглашение расширено до версии 2026-08-30-v2 структурными SaaS-разделами; шесть связанных информационных документов перечислены отдельно и не входят в clickwrap-акцепт.
-->
