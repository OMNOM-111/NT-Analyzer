# ADR-0003: Trusted devices и step-up authentication


- Статус: Принято
- Дата решения: 2026-08-01
- Уточнение решения: 2026-09-02

## Решение

Устройство имеет случайный UUID и server-side lifecycle `pending -> trusted -> revoked|expired`. User-Agent, модель ОС и IP — только ограниченная audit metadata; IP никогда не является device identity. Пользователю показываются короткие понятные сведения: тип устройства, ОС/браузер, последнее использование и состояние.

Новое устройство начинает как `pending`. Доверие выдаётся только после step-up через уже подтверждённый Telegram и/или verified email согласно политике действия. Отзыв устройства немедленно инвалидирует связанные sessions и Connector access.

Security challenges одноразовые, ограничены по времени и попыткам, хранят только hash секрета и имеют purpose binding. Повторное использование, смена пользователя или окружения запрещены.

Security events хранятся 180 дней. IP сохраняется минимально и маскированно; secrets, OTP и полные токены в audit не попадают.

## Уточнение: Machine → Client → Session

Слово «устройство» в прежнем lifecycle означает client credential (профиль
браузера или установку приложения), а не автоматически доказанный физический
компьютер. Physical Machine создаётся и показывается только при
hardware-bound Connector identity или attested pairing. IP, hostname,
User-Agent, browser version, VPN и approximate location являются audit
metadata и не могут создавать или связывать Machine. Unbound browser/app
остаётся отдельным Client.

Новый human login по умолчанию создаёт session в `pending` с TTL около пяти
минут. До подтверждения точный server allowlist содержит только auth bootstrap,
challenge/confirm/approve/resend/reject и logout; остальные protected requests
получают `403 DEVICE_CONFIRMATION_REQUIRED`. По истечении окна session
инвалидируется без silent fallback.

Device confirmation использует только подтверждённый Telegram или verified
email и требует явный `trust_mode`:

- `permanent` — Client становится trusted до явного revoke; следующие sessions
  этой же client credential наследуют trust;
- `session` — active становится только текущая `session_id`; Client остаётся
  pending, следующая session снова требует OTP, cookie остаётся непостоянной.

Режим с фиксированным суточным TTL не является частью текущего решения.
Machine trust не передаётся неизвестному Client без доказанной binding-процедуры.
Отзыв Client завершает только его sessions, отзыв Machine каскадирует на
связанные Clients/sessions, а завершение Session не отзывает permanent trust.

## Критические действия

Step-up обязателен для связывания/объединения identity, доверия нового устройства, personal NinjaTrader pairing, revoke Connector, смены default account, изменения trading capability и release/deployment approvals.
