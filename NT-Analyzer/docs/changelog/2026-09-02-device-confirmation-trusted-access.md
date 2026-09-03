# Device Confirmation and Trusted Access — Development

Release title: Device Confirmation / Trusted Access

Change summary: Каждый новый неизвестный browser/app access теперь получает
короткую pending-сессию и не допускается к продуктовым API до одноразового
подтверждения через Telegram или verified email. Пользователь выбирает
постоянное доверие либо доступ только для текущей auth-session.

Source branch: `codex/device-confirmation-trusted-access`

Core implementation commit: `19e0f43a35bee5a2e396538962e8f24e92bed6ef`

Pull request: [#278](https://github.com/OMNOM-111/NT-Analyzer/pull/278)

Verification result: `PASS (Development)` — full clean-base regression,
focused auth/device tests, all eight local acceptance scenarios, static gates
and the production-bundle pre-release check are green.

Release impact: Development only. Canary and Production were not changed;
merge, build, release and deployment require separate owner decisions.

## User result

1. ✅ Первый неизвестный access создаётся как `pending`; backend сокращает его
   TTL примерно до пяти минут.
2. ✅ Доступ можно подтвердить как `permanent` или `session`. Варианта «24 часа»
   в новом контракте и UI нет.
3. ✅ Код отправляется только через подтверждённый Telegram или verified email;
   шесть цифр, TTL, число попыток, cooldown и resend enforced сервером.
4. ✅ После кода показывается отдельное состояние «Доступ подтверждён» с
   клиентом, ОС, режимом и маскированными audit-данными.
5. ✅ «Безопасность» разделена на «Устройства», «Мои сессии» и «История входов».
6. ✅ Каждая новая неизвестная browser/app credential проходит тот же flow;
   permanent credential повторно не запрашивает OTP, session-only не наследуется.
7. ✅ Пользователь может переименовать machine/client, завершить одну session,
   отозвать client или каскадно отозвать доказанную machine.
8. ✅ Machine → Client → Session показывается только при доказанной привязке;
   unbound и remote clients остаются отдельными и не превращаются в фиктивные
   компьютеры.

## Reused foundations

- существующий UUID trusted-client registry и PostgreSQL JSONB document mirror;
- существующие PBKDF2 OTP hashes, purpose/user/device/environment binding,
  ограничение попыток и реальные Telegram/e-mail delivery adapters;
- существующая hardware-bound Connector machine identity и одноразовый pairing;
- существующие client/machine/session revoke scopes и audit trail.

Новый OTP-механизм, browser fingerprinting или альтернативный device store не
создавались.

## Final model and policy

- `Machine` существует только при hardware-bound Connector credential или
  attested pairing. IP, hostname, User-Agent, browser version, VPN и
  геолокация не доказывают machine identity.
- `Client` — отдельная browser profile/app credential. Без доказанной machine
  он возвращается в `standalone_clients`.
- `Session` — конкретный вход и единственный носитель режима `session`.
- `permanent` записывается на client и действует до явного revoke. Повторный
  login той же credential получает normal session без нового OTP.
- `session` записывается только в текущую session; client остаётся pending.
  Logout, revoke или server expiry завершают доступ, а следующий login снова
  pending. Browser cookie не получает `Max-Age`.
- Pending session может вызвать только точный allowlist challenge/confirm/
  approve/resend/reject/logout. Остальные защищённые запросы получают
  `403 DEVICE_CONFIRMATION_REQUIRED`; expired pending session получает
  `401 device_confirmation_expired`.
- Ранее выданные legacy sessions без trusted-client UUID доживают до своего
  исходного expiry, чтобы включение фичи не стало массовым logout. Все новые
  human sessions fail closed.

## API changes

- `GET /api/auth/status` — для pending возвращает только минимальный bootstrap
  и `device_access`; workspace, capabilities и продуктовые данные не загружает.
- `GET /api/account/security` — добавлены нормализованные `machines`,
  `standalone_clients`, `sessions`, `login_history`, `confirmation_channels`
  и явная `grouping_policy`; старые плоские поля временно сохранены.
- `POST /api/account/security/challenge` — принимает `trust_mode`; challenge
  привязан к текущей session.
- `POST /api/account/security/challenge/resend` — серверный cooldown и предел
  повторов.
- `POST /api/account/devices/approve` — применяет `permanent | session`.
- `POST /api/account/devices/rename` и `/api/account/machines/rename` —
  self-service rename в scope текущего user.
- Существующие `/devices/revoke`, `/machines/revoke` и `/sessions/revoke`
  используются как три разных действия с разной областью.

## Storage and migrations

Новых SQL migrations нет. Новые session/challenge поля находятся в уже
существующем JSONB `document`; нормализованные `sf_auth_sessions`,
`sf_trusted_devices`, `sf_physical_devices` и `sf_security_challenges`
синхронизируются прежним transactional repository.

## Isolation and compatibility

- SF Chat и Community UI, routes, storage и business logic не изменялись.
- Dev preview, test-auth, service accounts и impersonation помечены явным
  confirmation exemption; production human-login helpers по умолчанию требуют
  подтверждение.
- Неизвестный remote/AI browser получает нейтральное имя browser/client, если
  signed integration identity отсутствует; конкретный продукт не угадывается.

## Verification evidence

- `tests/test_device_confirmation_flow.py`: pending guard, minimal bootstrap,
  permanent/session semantics, next-login behavior, session/mode binding,
  timeout, resend cooldown/limit, unbound grouping, IP change, rename/revoke
  scope, cookie persistence and UI wording.
- Clean-base repository regression: `2507 passed, 34 skipped`.
- Focused post-rebase auth/device/security regression: `280 passed`.
- Acceptance 1→8: all PASS in eight separate invocations (`28` selected tests).
- Repository-root static scan: CSP, secrets and Markdown PASS; modified Python
  compiles, shipped JavaScript parses, `git diff --check` and External GPT
  Context validation PASS.
- Production bundle pre-release check: `476` shipped files; static scan,
  runtime reads, Python compile and JavaScript syntax all PASS.
- The PR diff is one commit over `origin/main` and contains no Community or
  SF Chat paths.
- Manual visual/design acceptance and live delivery on Canary/Production are
  separate from automated Development verification.
