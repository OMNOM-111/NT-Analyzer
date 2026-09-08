# E-mail registration — восстановление после истёкшего OTP

Дата: 2026-09-08. AI-assisted change. Ветка:
`codex/agent-world-unified-acceptance`, исходный SHA
`1409553a46d0dffa7ef329b28029d93f68b405d7` + текущий интеграционный WIP.
Без merge, deploy, смены версии или изменения рабочих Local-данных.

## Воспроизведённый дефект

В текущем UI кнопка «Подтвердить e-mail» при регистрации сохраняет challenge/code
в draft и открывает финальный экран. Реальная OTP-проверка происходит при
«Создать профиль», после ручного согласия; промежуточная кнопка не расходует
backend proof второй раз. Код сохраняет исходный TTL **600 секунд**, поэтому
долгая задержка на любом из экранов может законно завершиться HTTP 410.

`verify_email_auth` при expired/consumed challenge возвращал 410 без machine
code. E-mail-ветка `complete_registration` передавала ошибку как есть, а
существующий `renderStep3.catch` в `ui.js` возвращает на шаг проверки только
при `code == registration_expired`. В результате на финальном экране повторно
отправлялся тот же непригодный proof.

Это подтверждает воспроизводимый механизм ошибки, но не устанавливает возраст
конкретного challenge из ручного browser-прохода: его runtime store не читался.

## Узкая правка

Только `app/account_auth.py`, e-mail-ветка `complete_registration`:
`AccountAuthError.status == 410` преобразуется в тот же HTTP 410 с
`code=registration_expired` и понятным предложением запросить новый код.
Другие ошибки, включая `email_code_invalid`, сохраняются без изменений.

Не изменялись TTL, порядок ручного consent, одноразовость, создание сессии,
Device Confirmation, login/link verify, synthetic provider или UI. Уже
существующий UI hook может вернуть пользователя на verification. Запрос нового
кода остаётся явным действием пользователя.

## Evidence

Новый `tests/test_email_registration_lifecycle.py` использует существующие
изолированные Development/Preview fixtures и локальные управляемые часы:
fresh proof, отсутствие consent, граница TTL, consumed/replay, неверный код,
неизвестный e-mail при login без consent, явный новый OTP после expiry.
Ни provider, ни браузер, ни работающий Preview/Local этим исполнителем не
использовались; реальные ключи не читались.

- До правки: **8 failed, 14 passed**; все 8 failures воспроизвели именно
  отсутствующий `registration_expired`, при корректном HTTP 410.
- После правки: новый lifecycle + `test_auth_onboarding.py` +
  `test_first_device_after_registration.py` + `test_preview_sandbox.py`:
  **72 passed, 0 skipped**, 18.19 s.
- `py_compile` account auth и нового test-файла — PASS.
- Scoped `git diff --check` — PASS.

Browser acceptance этого исправления — **PENDING** у root исполнителя после
перезапуска только его собственного QA instance: backend-модуль загружается
процессом при старте. Unit/contract PASS не заменяет ручной проход. Чекбокс
consent и финальное создание профиля не подтверждались автоматически.

Git/current-docs/External GPT Context Pack closeout объединяет root; этот
исполнитель не stage/commit/push. Release impact: только будущая интеграция
этого compatibility fix, не изменение доступного owner Local 8765.
