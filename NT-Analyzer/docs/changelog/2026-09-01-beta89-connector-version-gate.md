# beta.89 - Connector Version Gate

Release summary: Поддержка runtime-каталога определяется базовой версией Connector, а не счётчиком -dev, поэтому новый Connector действительно получает команду снимка каталога; без этого страничная доставка из beta.88 не работала бы ни на одной разумно пронумерованной сборке.
Release PRs: #263
Affected subsystems: Connector protocol version gate
Release impact: Разблокирует выпуск нового Connector; поведение уже установленных версий не меняется.

## Что вошло

- PR #263: `_connector_supports_runtime_catalog` читал только хвост `-dev.N`, из-за чего `0.4.3-dev.1` считался старее `0.4.2-dev.17`. Строго более новый Connector никогда не получал команду `snapshot_runtime`, сервер оставался на голых корнях, и восстановиться апгрейдом было невозможно.
- Теперь решает базовая версия; prerelease точной базовой версии по-прежнему обязан быть не ниже сборки, в которой функция появилась, а финальный релиз этой базы содержит её всегда.

## Совместимость

| version | до | после |
|---|---|---|
| `0.4.2-dev.16` | False | False |
| `0.4.2-dev.17` | True | True |
| `0.4.2` | True | True |
| `0.4.3-dev.1` | False | **True** |
| `0.5.0-dev.1` | False | **True** |

Уже установленные версии сохраняют прежнее поведение.

## Release sequence

`final main -> mandatory CI -> one signed immutable artifact -> Canary acceptance -> same artifact without rebuild -> Production`

Операционные candidate, build, artifact hashes, результат Canary и Production дописываются сюда после завершения живого релиза.
