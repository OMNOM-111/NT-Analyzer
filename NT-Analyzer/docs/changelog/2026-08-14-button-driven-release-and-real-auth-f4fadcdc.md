# Кнопочный релиз и реальная Google/email аутентификация (`f4fadcdc`)

Дата записи: `2026-08-14` UTC. Первый релиз, выполненный целиком через Release
Center: LOCAL DEV → кнопка Canary → проверка owner → кнопка Production. Ни одной
ручной SSH- или git-команды в самом релизе.

## Live identity

| Field | Value |
| --- | --- |
| Git SHA | `f4fadcdca13a7e0ffc538664e182f290cc344a2b` |
| Build ID | `sf-0.10.0-beta.1-f4fadcdca13a-20260814T231259Z` |
| Archive SHA256 | `85F0611B9D409EFC162E820B50883B8A1494B2B0561AE4F40D8B2F8288A17359` |
| Manifest SHA256 | `C840E2A67C68F79BB3DABD08F19C506082D368868F8D947D4DA2F4B3F490AD49` |
| Canary | `https://canary.stratforges.com` |
| Production | `https://app.stratforges.com` |

Один артефакт, восемь blue/green стадий `pass` на обоих окружениях, финальное
состояние кандидата `production_live`.

## Release Center

Реальный executor (`stage9_ssh`) уже был в коде; включён на LOCAL DEV через
`STRATFORGE_RELEASE_DEPLOY_ADAPTER` и SSH-настройки в локальном secret store.
Кнопочная последовательность: «Новый релиз-кандидат» → «Собрать артефакт» →
«Проверить подпись» → «Развернуть в Canary» → «Отметить проверку: PASS» →
«Одобрить Production» → «Продвинуть в Production» → «Подтвердить
production_live». Кнопка «Откатить Production» доступна из `production_live`.

Три дефекта, из-за которых кнопочный путь не работал вовсе:

1. `_git_root()` декодировал вывод git консольной локалью — checkout с
   кириллицей ломался, каждая сборка падала с WinError 267 (PR #44).
2. Рендер governance при старте dev-сервера оставлял worktree грязным, а
   Release Center отказывается собирать из грязного дерева (PR #43, #45).
3. Упавший Canary-деплой нельзя было повторить тем же артефактом — только
   пересобрать (PR #46).

## Аутентификация

| Провайдер | Canary | Production |
| --- | --- | --- |
| Telegram | `configured` | `configured` |
| Google | `configured`, отдельный client id | `configured`, отдельный client id |
| Email (Resend) | `operational`, отдельный ключ | `operational`, отдельный ключ |

Callback URI в коде строится как `{origin}/api/auth/google/callback`. Проверено
против Google: оба окружения получают `302` на страницу входа Google, то есть
client id и redirect URI приняты — без `redirect_uri_mismatch` и
`invalid_client`.

Email-доставка подключена к существующему `/api/auth/email/start|verify` через
Resend. При настроенном провайдере одноразовый код больше не возвращается в
браузер. Перед `api.resend.com` стоит Cloudflare, отклоняющий дефолтный
`Python-urllib` (ошибка 1010) — клиент передаёт явный User-Agent.

## Проверено на живых окружениях

- Owner Telegram-вход по реальному пути shared-бота на обоих окружениях.
- Все owner-поверхности HTTP 200 на обоих окружениях.
- Изоляция сессий 24/24: анонимный запрос отклонён; Canary-сессия не
  аутентифицируется на Production; Canary-сессия работает на Canary.
- Повторный вход существующего owner даёт тот же identity UUID; дублей
  идентичности нет (Production 5 пользователей / 5 уникальных id, Canary 1/1).

## Внешние блокеры

- **Домен `stratforges.com` не верифицирован в Resend.** Ключи ограничены
  только отправкой, поэтому сейчас используется общий песочный отправитель
  `onboarding@resend.dev`. Регистрация произвольных новых пользователей по
  email заработает только после верификации домена и публикации DNS-записей;
  после этого достаточно поменять `NTA_EMAIL_AUTH_FROM` — без пересборки.
- Завершение входа через Google требует пароля владельца, а чтение письма с
  кодом — доступа к почтовому ящику. Проверено всё до этих двух шагов.
