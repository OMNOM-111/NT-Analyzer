# ADR-0003: Trusted devices и step-up authentication


- Статус: Принято
- Дата решения: 2026-08-01

## Решение

Устройство имеет случайный UUID и server-side lifecycle `pending -> trusted -> revoked|expired`. User-Agent, модель ОС и IP — только ограниченная audit metadata; IP никогда не является device identity. Пользователю показываются короткие понятные сведения: тип устройства, ОС/браузер, последнее использование и состояние.

Новое устройство начинает как `pending`. Доверие выдаётся только после step-up через уже подтверждённый Telegram и/или verified email согласно политике действия. Отзыв устройства немедленно инвалидирует связанные sessions и Connector access.

Security challenges одноразовые, ограничены по времени и попыткам, хранят только hash секрета и имеют purpose binding. Повторное использование, смена пользователя или окружения запрещены.

Security events хранятся 180 дней. IP сохраняется минимально и маскированно; secrets, OTP и полные токены в audit не попадают.

## Критические действия

Step-up обязателен для связывания/объединения identity, доверия нового устройства, personal NinjaTrader pairing, revoke Connector, смены default account, изменения trading capability и release/deployment approvals.
