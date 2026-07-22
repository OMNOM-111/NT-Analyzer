# Установка StratForge Connector для NinjaTrader 8

Статус: инструкция для проверенного пакета; публичная Production-ссылка появится
после Authenticode/release gate.

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
   version, NT instance, masked account labels, fingerprint и свежий heartbeat.

Private device key и bootstrap защищены Windows DPAPI CurrentUser. В открытом
конфиге нет enrollment code или broker credentials. Connector открывает только
исходящее TLS-соединение и не создаёт публичный входящий порт.

## Repair и удаление

«Восстановить» повторно проверяет подпись и хэши пакета, сохраняет config/device
key и атомарно возвращает правильный DLL. «Удалить» сначала делает ещё один
backup, затем восстанавливает DLL/config, существовавшие до первой установки.
Локальные ключи, журнал и recovery backup по умолчанию сохраняются, чтобы
удаление можно было расследовать или отменить.

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
