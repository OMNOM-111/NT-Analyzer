# Установка StratForge Connector для NinjaTrader 8

История поправки: 2026-08-09T00:57:35Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: приёмочный аудит кнопки подключения личного NinjaTrader, consent-gate, release catalog и безопасного updater.

Статус: инструкция для проверенного пакета; публичная Production-ссылка появится
после Authenticode/release gate.

## Что делает кнопка «Подключить свой NinjaTrader»

Backend возвращает установщик только из канала `stable` проверенного Connector
release catalog. Ответ содержит immutable URL, version, SHA-256 архива и
manifest. Если catalog отсутствует или невалиден, UI обязан показать точную
блокировку, а не фиктивную ссылку.

После согласия пользователя браузер скачивает подписанный пакет. Windows всё
равно требует явного запуска Setup и, при необходимости, UAC: скрытая установка
компонентов из браузера не поддерживается и не должна имитироваться. Setup уже
автоматизирует поиск каталога NinjaTrader, установку Connector, регистрацию
updater и последующий signed hello/heartbeat.

## Установка

1. В кабинете StratForge откройте «Мой NinjaTrader» и получите одноразовый код.
   Он действует 10 минут и используется только один раз.
2. Скачайте один ZIP `StratForge.Connector-<version>-stable.zip` только по ссылке
   из кабинета. Не скачивайте отдельный DLL из сообщений или чужих сайтов.
3. Распакуйте ZIP и запустите `INSTALL.cmd` либо
   `StratForge.Connector.Setup.exe`.
4. Проверьте найденный каталог `Documents\NinjaTrader 8`. Если каталог другой,
   нажмите «Выбрать» и укажите именно пользовательский каталог NinjaTrader.
5. Закройте NinjaTrader самостоятельно. Установщик никогда не завершает торговый
   терминал автоматически.
6. Введите одноразовый код и нажмите «Установить». Пароли брокера, API keys и
   данные счёта не требуются.
7. После сообщения об успехе запустите NinjaTrader. В кабинете должны появиться
   version, NT instance, masked account summaries, фактический режим
   `paper/demo/live/playback/unknown`, fingerprint и свежий heartbeat.

Private device key и bootstrap защищены Windows DPAPI CurrentUser. В открытом
конфиге нет enrollment code или broker credentials. Connector открывает только
исходящее TLS-соединение и не создаёт публичный входящий порт.

## Repair и удаление

«Восстановить» повторно проверяет подпись и хэши пакета, сохраняет config/device
key и атомарно возвращает правильный DLL. «Удалить» сначала делает ещё один
backup, затем восстанавливает DLL/config, существовавшие до первой установки.
Локальные ключи, журнал и recovery backup по умолчанию сохраняются, чтобы
удаление можно было расследовать или отменить.

## Автоматическое обновление

Пакет устанавливает отдельный `StratForge.Connector.Updater.exe`. AddOn получает
предложение stable/canary только внутри аутентифицированной Connector-сессии.
Updater скачивает ZIP во временный файл, проверяет его SHA-256, P-256 подпись
manifest и хэш каждого файла, после чего лишь подготавливает обновление.

Если NinjaTrader открыт, DLL не меняется и терминал не закрывается. Замена
происходит после ближайшего обычного закрытия NinjaTrader: updater сохраняет
last-known-good, запускает verified Setup и ждёт от новой версии успешные signed
hello + heartbeat. Если health-check отклонён или истёк, при следующем безопасном
закрытии восстанавливается предыдущая DLL/config. Один и тот же неудачный релиз
автоматически повторно не ставится. Device key и DPAPI state при update/rollback
не перезаписываются. Major/protocol update требует отдельного подтверждения.

Production-ready считается только состояние, где stable release опубликован в
catalog, Authenticode и manifest signature проверяются, URL не является
placeholder, а новый Connector прошёл signed hello + heartbeat. До этого кнопка
честно остаётся заблокированной.

## Понятные причины отказа

- `NinjaTrader is running` — закройте его вручную и повторите;
- `manifest signature ... invalid` / `payload hash mismatch` — удалите пакет и
  скачайте заново из кабинета; не обходите проверку;
- `local_development config requires explicit migration` — старый developer
  bridge найден; обычному внешнему пользователю это не встречается, владельцу
  нужна подтверждённая migration/rollback операция;
- `enrollment code is required` — получите новый код в выбранном workspace;
- `unsupported config field` — config не изменяется молча; передайте diagnostics
  поддержке.

Для diagnostics можно открыть Setup и выбрать repair либо выполнить
`StratForge.Connector.Setup.exe --diagnostics --ninja-user-dir "..."`. Вывод не
содержит code/private key. Не присылайте поддержке содержимое DPAPI-файлов.

Состояние updater проверяется командой
`StratForge.Connector.Updater.exe --diagnostics --ninja-user-dir "..." --state-root "..."`.
Журнал `update-journal.jsonl` содержит только version/result/reason/timestamp и
не содержит pairing code, device key или broker data.
