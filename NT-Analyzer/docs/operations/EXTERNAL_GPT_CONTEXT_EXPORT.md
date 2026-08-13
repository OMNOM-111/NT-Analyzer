# External GPT Context Export

Канонический source-of-truth для внешнего GPT-контекста находится только в
`docs/external-gpt-context/`. Папка экспорта на рабочем столе не является
документацией проекта и не редактируется вручную.

## Команда

Из `NT-Analyzer/`:

```powershell
python tools/export_external_gpt_context.py
```

По умолчанию экспорт идёт в:

```text
C:\Users\dimon\Desktop\StratForge External GPT Context
```

Можно указать другой каталог:

```powershell
python tools/export_external_gpt_context.py --output-dir "D:\Exports\StratForge External GPT Context"
```

## Что делает скрипт

- сначала запускает validator Context Pack;
- удаляет только ранее созданные им export-копии по собственному manifest;
- копирует ровно 15 canonical `.md` файлов `00`–`14` без изменений имён и содержания;
- создаёт `EXPORT_INFO.txt` с датой экспорта, Git SHA и напоминанием, что этот `.txt` загружать не нужно;
- не экспортирует tests, validator, runtime files, secrets или исходный код.

## Что загружать во внешний ChatGPT Project

Загружать только 15 markdown-файлов `00`–`14` из export-папки.
`EXPORT_INFO.txt` и служебный manifest загружать не нужно.