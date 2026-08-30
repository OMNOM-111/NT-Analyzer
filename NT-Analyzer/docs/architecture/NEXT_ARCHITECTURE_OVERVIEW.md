# Next Architecture: границы системы


Подробные решения находятся в [ADR index](../adr/README.md), план выполнения — в [NEXT_ARCHITECTURE_PROGRAM_STATUS.md](../current/NEXT_ARCHITECTURE_PROGRAM_STATUS.md).

```mermaid
flowchart LR
  D["Development\nлокальные data и test providers"] --> A["Immutable artifact\nmanifest + signature + SHA-256"]
  A --> C["Canary\nотдельные DB, secrets, queues, bot и Connector sessions"]
  C --> G{"Checks PASS + owner approval\nтот же artifact SHA"}
  G --> P["Production\nblue-green switch"]
  U["UUID user"] --> I["Telegram / Google / Email identities"]
  U --> T["Trusted devices + step-up"]
  U --> W["Workspace"]
  W --> N["Personal NT + Agent Team"]
  W --> Q["Owner-training NT\nКоординатор + durable lease"]
  O["Owner / explicit developer grants"] --> M["Admin Panel capabilities"]
  M --> G
```

## Непересекаемые границы

| Граница | Инвариант |
|---|---|
| Environment | Нет общей writable state, secrets, cookies, Telegram updates или Connector sessions |
| Identity | Внешний provider subject не является внутренним user ID |
| Device | IP/User-Agent не являются device identity; критические действия требуют step-up |
| Authorization | UI visibility повторяет, но не заменяет server-side capability check |
| Release | Canary и Production получают тот же immutable artifact без rebuild |
| NinjaTrader | Personal runtime не падает обратно на общий owner-training runtime |
| Documents | Workspace/strategy revision не меняет global governance и safety limits |

Phase 0 документирует решения и не меняет Production behavior.
