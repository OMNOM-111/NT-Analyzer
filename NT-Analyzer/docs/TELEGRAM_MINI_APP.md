# Telegram Mini App

Aurora UI обслуживается тем же локальным backend на `127.0.0.1:8765`. Наружу
публикуется только HTTPS-туннель; backend не начинает слушать `0.0.0.0`.

## 1. Туннель

Рекомендуется постоянный named tunnel с собственным hostname. Пример
`cloudflared` config:

```yaml
tunnel: YOUR-TUNNEL-UUID
credentials-file: C:\Users\you\.cloudflared\YOUR-TUNNEL-UUID.json
ingress:
  - hostname: stratforge.example.com
    service: http://127.0.0.1:8765
  - service: http_status:404
```

Запуск:

```powershell
.\start-mini-app-tunnel.ps1 -TunnelName stratforge
```

Или из desktop Aurora: `Системные действия → Telegram → Запустить Mini App`.
Backend поднимет `cloudflared` в фоне, включит удалённый доступ и проверит
публичный URL.

Для краткой проверки можно использовать `-Quick`, но URL quick tunnel меняется
после перезапуска и поэтому непригоден для постоянного Menu Button. Не открывайте
порт 8765 на роутере. Для другого reverse proxy обязательно сохраняйте исходный
`Host` или передавайте `X-Forwarded-Host`; клиентский адрес — в
`X-Forwarded-For`.

## 2. Бот и Menu Button

1. В desktop Aurora откройте `Системные действия → Telegram`, сохраните bot
   token и подключите личный чат владельца.
2. В блоке `Telegram Mini App` укажите публичный `https://...` URL и сохраните.
3. Нажмите `Настроить Menu Button`. Backend вызовет Bot API
   `setChatMenuButton` с URL `<public-url>/ui/`.
4. Эквивалентная ручная настройка в BotFather: `/setmenubutton` → выбрать бота →
   текст `StratForge AI` → URL `<public-url>/ui/`.
5. Оставьте удалённый доступ выключенным до добавления первого пользователя.

## 3. Выдача и отзыв доступа

1. Пользователь открывает desktop UI или Mini App и нажимает
   `Авторизоваться через Telegram`.
2. Backend создаёт одноразовую ссылку входа. Код действует 15 минут и
   используется один раз.
3. Пользователь нажимает `Start`, затем отправляет контакт кнопкой
   `requestContact`. Backend требует `contact.user_id == message.from.id`.
4. Пользователь заполняет недостающие обязательные поля: имя, фамилию и e-mail.
5. Последний фактор для нового аккаунта — владелец нажимает
   `Разрешить аккаунт` в личном чате бота. До этого статус остаётся `pending`.
6. Роль можно изменить, а доступ — отозвать в любой момент. Каждый API-запрос
   заново читает whitelist, поэтому отзыв действует сразу.

Владелец также может отправить боту `/access` и отозвать пользователя кнопкой
в личном чате.

`has_private_forwards` и имя/username не используются как фактор личности.

## 4. Security contract

- Mini App добавляет `X-Telegram-Init-Data` во все `fetch`/SSE API-запросы.
- Обычный desktop-браузер получает случайную 384-битную HttpOnly-сессию после
  Telegram-проверки. Изменяющие запросы дополнительно требуют CSRF token и
  same-origin `Origin`.
- Backend проверяет Telegram WebApp HMAC по bot token, `auth_date` (не старше
  15 минут), `user.id`, состояние общего выключателя, whitelist и роль.
- `read_only` допускает только GET/HEAD. POST/DELETE требует `full_control`.
- Из Mini App всегда запрещены `/api/ops/live/*`, live unlock, перезапуск
  backend и управление Telegram/whitelist. Существующие paper/demo approve-gates
  выполняются после Mini App guard и не ослабляются.
- Лимит: 180 чтений и 45 изменений в минуту на пару user/IP.
- CSP разрешает Telegram WebView framing, сохраняя `default-src 'self'`.
- Аудит пишется в `data/audit/telegram-mini-app.jsonl`: UTC timestamp,
  `source=telegram_mini_app`, user id, роль, method/path, status, tunnel IP и
  forwarded IP. Файл и whitelist являются локальными gitignored-данными.
- Профили, телефоны, e-mail, pending-заявки и хеши сессий находятся в
  `data/integrations/accounts.dpapi`, зашифрованном Windows DPAPI CurrentUser.
  Plaintext персональных данных в JSON-настройках нет.

Если Mini App сообщает, что `initData` истёк, закройте и заново откройте её из
Menu Button. Это создаст новый подписанный Telegram launch context.
