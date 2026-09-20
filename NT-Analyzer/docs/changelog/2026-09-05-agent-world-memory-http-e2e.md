# Agent World — HTTP-проверка публикации и отзыва Memory

Release title: Memory sharing — ordinary-session HTTP isolation evidence.

Change summary: добавлена независимая интеграционная проверка публикации выбранной
Memory и немедленного прекращения доступа по ранее известным ссылкам после отзыва,
истечения TTL, изменения источника или потери пользовательского доступа. Runtime-код
и данные владельца этот slice не изменяет.

Source checkpoint: активный Local `95912cbff8152905966e6bb7bfc2a45d3db15f80`,
`0.10.0-beta.96`. Работа выполняется в `codex/agent-world-owner-preview` для
[draft PR #282](https://github.com/OMNOM-111/NT-Analyzer/pull/282). Итоговый source
commit и общий Git/CI closeout фиксирует основной исполнитель после интеграции;
результаты ниже относятся к проверенному рабочему дереву, не объявляют релиз.

## Что проверяется

Новый `tests/test_agent_world_memory_http_e2e.py` поднимает настоящий
`server.Handler` на одноразовом loopback-порту. Три явно synthetic fixture identity
проходят обычный cookie-session путь, не Owner Preview и не Local owner bypass:
автор личной рабочей области, её read-only участник и пользователь другой области.
У всех `is_owner=false`, нет service/Preview identity и нет реальных credentials.

Не подменяются Handler routing/body/device/CSRF/permission enforcement,
`domain_gateway`, `DomainService`, grant/artifact чтение или SQLite. Подменены
только lookup-границы auth/session/membership/entitlement. Все stores одноразовые,
runtime data roots изолированы; сетевые соединения разрешены только к тестовому
HTTP listener. Rate limiter отключён только тестовой Development-конфигурацией и
не входит в доказательство этого slice.

26 новых сценариев доказывают:

- Private Memory и её artifact недоступны второму пользователю; одно promotion
  не публикует данные. После явной публикации доступны только выбранный content
  и publication proof, без private review reason или private evidence bytes.
- Общая ссылка на Memory-artifact не открывает private artifact API, исходные
  доказательства или приватное подтверждение автора. Ответы имеют `no-store`,
  CSP sandbox, `nosniff` и ETag, совпадающий с SHA256 фактических байтов.
- Read-only участник не может create/update/promote/revoke/republish, даже если
  роль его сессии меняется на `full_control`: отдельная membership-проверка
  остаётся обязательной. Отказы не переписывают domain DB.
- Отзыв публикации, отзыв приватного источника и его канонический переход
  `active → superseded` закрывают detail/list/content/proof по тем же сохранённым
  URL. Активный источник нельзя незаметно переписать через HTTP.
- TTL проверен до и после фактического истечения времени без подмены clock в
  HTTP reader. Setup использует предусмотренную `DomainService.now` инъекцию
  для старого однодневного grant с коротким оставшимся сроком; GET не меняет
  записи/history. Supersession также является канонической fixture-транзакцией,
  а не новым пользовательским API или разрешением редактировать active Memory.
- Другая workspace, отозванная сессия, stale session snapshot, отозванное
  membership, pending device и неизвестная cookie не открывают прежние URL.
  CSRF автора нельзя заменить CSRF другого пользователя или пропустить.

## Verification result

**PASS — 190 passed**, 88.91 s, без пропусков:

```text
python -m pytest tests/test_agent_world_memory_http_e2e.py tests/test_agent_world_domain_service.py tests/test_agent_world_domain_gateway.py tests/test_agent_world_session_authority.py -q
```

В эту выборку входят все 26 новых HTTP-сценариев. Повторный standalone прогон
нового файла: **26 passed**, 18.33 s, без пропусков. Python compilation и
проверка trailing whitespace двух новых файлов — PASS. Первая setup-попытка создать новую same-state revision у active
Memory была правильно отвергнута existing immutable-contract; fixture исправлен
на разрешённый `active → superseded`, без изменения production-кода.
Общий full regression/static/context/bundle/CI выполняет основной исполнитель.

Это реальный HTTP/SQLite integration test с **synthetic тестовыми аккаунтами**,
не ручная проверка двух живых пользователей. Multi-user visual acceptance,
отдельная регистрация/ключ и остальные owner-dependent сценарии не получают
статус PASS из этих тестов. Связанные current/External GPT документы обновляет
основной исполнитель в общем интеграционном commit.

## Release impact и rollback

Изменены только новый тестовый файл и эта scoped запись. API/schema, права,
модельные ключи, бюджеты, очереди, Auth/devices/Preview, SF Chat/Social,
market data/Connector/trading и существующие owner данные не меняются.
Номер версии не меняется; merge, deploy, подписывание и Production/Canary DB
не выполнялись. Rollback этого slice — убрать тест/запись из последующего
изменения; восстанавливать или удалять runtime данные не требуется.

`IMPLEMENTATION COMPLETE: YES` для автоматизированного test slice.
`GIT CLOSEOUT COMPLETE: PENDING ROOT INTEGRATION`.
`STAGE CLOSED: NO` — live-user acceptance и полный Agent World остаются отдельно.
