# ADR-0006: NinjaTrader ownership, агенты и resource lease

История поправки: 2026-08-02T00:53:55Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: Phase 0 — утвердить границу личного и общего NinjaTrader.

- Статус: Принято
- Дата решения: 2026-08-01

## Решение

Personal NinjaTrader принадлежит конкретному workspace и получает изолированную Agent Team. Он никогда не переключается на owner-training runtime как fallback.

Пользователь с разрешением на общий owner-training NinjaTrader получает одного агента `Координатор`, расположенного ниже Виктора. Координатор ставит задачи разрешённым специалистам, но не раскрывает owner-only контекст или личности других пользователей.

Конфликтующие backtest/optimization операции общего NinjaTrader защищаются durable resource lease с queue, TTL, heartbeat, cancellation и recovery. Read-only telemetry может выполняться параллельно, если её capability явно безопасна. Пользователь видит состояние «занят/в очереди» без чужих персональных данных; owner видит полную operational detail.

Истёкший lease освобождается детерминированно. Отмена новых shared jobs является безопасным rollback; personal connector остаётся независимым.
