# Task closeout protocol


## Цель

Протокол нужен, чтобы task не оставался в состоянии "код вроде готов, но Git и PR не закрыты". Для каждого stage отдельно фиксируются реализация, Git closeout, PR/CI и owner decision.

## Минимальный порядок закрытия

1. Зафиксировать текущую ветку, HEAD, remote tracking branch и наличие PR.
2. Проверить `git status --short --branch`.
3. Классифицировать все изменения: intentional code/docs, generated output, runtime data, local artifacts, unrelated dirty state.
4. Убрать из индекса runtime/local artifacts только разрешённым owner способом.
5. Восстановить date-only generated governance noise, если нет source-of-truth и amendment evidence.
6. Добавить или обновить документацию с видимой историей поправок: модель, Codex, owner request, UTC date, scope.
7. Выполнить focused tests и static checks, которые соответствуют blast radius.
8. Выполнить full available regression suite, если она не требует Production secrets, real trading или external destructive state.
9. Выполнить secret scan changed/added files.
10. Stage только точные пути. Не использовать `git add -A`.
11. Сделать commit с понятным scope.
12. Push task branch.
13. Создать или обновить draft PR, если owner не попросил ready PR.
14. Проверить CI/status checks и зафиксировать результат.
15. Финальный отчёт должен назвать commit SHA, branch, PR URL, tests, остаточный git status и Production boundary.
16. Если всё закрыто, задать ровно один merge-вопрос owner.

## Формулировка merge-вопроса

`Stage 10 Git closeout завершён: commit <SHA>, ветка <branch>, pull request <URL>, проверки <PASS/FAIL>. Объединить изменения с основной веткой? Да / Нет.`

Вопрос о merge не является Production confirmation. Любое Production действие должно запрашиваться отдельно.

## Запрещено без отдельного подтверждения owner

- merge в основную ветку;
- прямые изменения `main`;
- release, Canary deployment или Production deployment;
- доступ к Production secrets/server/DB;
- необратимые миграции;
- удаление локальных runtime данных, rollback bundles или внешних артефактов;
- старт следующей архитектурной фазы вместо closeout текущего stage.
