"""Small, offline benchmark fixtures and executors for the owner rehearsal.

These are real bounded computations over invented observations, not calls to
the named personas' LLMs. No provider, account, chart engine or trading adapter
is imported. Independent acceptance lives in ``demo_evaluation``.
"""
from __future__ import annotations

import hashlib
import json
from html import escape

from .states import ContractError


BENCHMARK_VERSION = "agent-world-synthetic-v1"
EXECUTOR = "local_deterministic"
PERSONAS = (
    {"key": "marina", "display_name": "Марина", "role": "Финансовый контролёр",
     "role_key": "accountant", "task_class": "synthetic_ledger",
     "title": "Проверить арифметику учебного журнала"},
    {"key": "tolik", "display_name": "Толик", "role": "Аналитик стратегий",
     "role_key": "strategy_analyst", "task_class": "synthetic_series",
     "title": "Рассчитать статистику синтетического ряда"},
    {"key": "nikita", "display_name": "Никита", "role": "Аналитик новостей",
     "role_key": "news_analyst", "task_class": "synthetic_events",
     "title": "Разобрать учебные события по приоритету"},
    {"key": "ivan", "display_name": "Иван", "role": "Оператор графиков",
     "role_key": "chart_operator", "task_class": "synthetic_chart",
     "title": "Построить график по проверенному учебному ряду"},
)
_SERIES = (
    (10000, 10003, 10001, 10006, 10008, 10005, 10009, 10012),
    (10012, 10009, 10011, 10005, 10002, 10006, 10001, 9998),
    (10000, 10007, 10002, 10009, 10003, 10008, 10004, 10006),
)


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def fixture(round_index: int) -> dict:
    """Three distinct fixed cases, never live quotes or independent market samples."""
    if type(round_index) is not int or not 0 <= round_index < len(_SERIES):
        raise ContractError("invalid_demo_round")
    closes = _SERIES[round_index]
    bars = []
    for index, close in enumerate(closes):
        opening = closes[index - 1] if index else close - 2
        bars.append({"minute": 570 + index, "open_ticks": opening,
                     "high_ticks": max(opening, close) + 2,
                     "low_ticks": min(opening, close) - 2,
                     "close_ticks": close, "volume": 120 + index * 17 + round_index * 11})
    return {"schema_version": 1, "source": "synthetic", "benchmark": BENCHMARK_VERSION,
            "fixture_id": f"{BENCHMARK_VERSION}-{round_index + 1}",
            "round": round_index + 1, "instrument": "DEMO — synthetic observations",
            "bars": bars,
            "ledger": {"initial_cents": 1000000,
                       "gross_cents": [1200 + round_index * 100, -300, 900, -450],
                       "fees_cents": [150, 150, 150, 150]},
            "events": [
                {"id": "event-a", "title": "Учебное расписание: публикация A",
                 "severity": 1 + round_index, "scheduled": True},
                {"id": "event-b", "title": "Синтетическое предупреждение B",
                 "severity": 4, "scheduled": False},
                {"id": "event-c", "title": "Учебная заметка C",
                 "severity": 1, "scheduled": False}],
            "disclaimer": "Invented benchmark. No market feed, broker, external AI or financial advice."}


def build_chart(source: dict) -> bytes:
    bars = source["bars"]
    floor = min(bar["low_ticks"] for bar in bars) - 2
    ceiling = max(bar["high_ticks"] for bar in bars) + 2
    points = []
    candles = []
    for index, bar in enumerate(bars):
        x = 100 + index * 100
        y = lambda value: 330 - (value - floor) * 250 / (ceiling - floor)
        colour = "#31d8b0" if bar["close_ticks"] >= bar["open_ticks"] else "#fc7b97"
        top = min(y(bar["open_ticks"]), y(bar["close_ticks"]))
        height = max(abs(y(bar["open_ticks"]) - y(bar["close_ticks"])), 2)
        candles.append(
            f'<g class="candle"><line x1="{x}" x2="{x}" y1="{y(bar["high_ticks"]):.2f}" '
            f'y2="{y(bar["low_ticks"]):.2f}" stroke="{colour}"/>'
            f'<rect x="{x-12}" y="{top:.2f}" width="24" height="{height:.2f}" '
            f'fill="{colour}" rx="3"/></g>')
        points.append(f'{x},{y(bar["close_ticks"]):.2f}')
    grid = "".join(f'<line x1="60" x2="885" y1="{y}" y2="{y}" stroke="#20384b"/>'
                   for y in (80, 142, 205, 267, 330))
    title = escape(f'Иван · {source["fixture_id"]}')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="960" height="420" '
           f'viewBox="0 0 960 420" role="img"><title>{title}</title>'
           '<rect width="960" height="420" rx="20" fill="#071422"/>'
           f'<text x="40" y="36" fill="#e3f1ff" font-family="sans-serif" font-size="19">{title}</text>'
           '<text x="40" y="59" fill="#91acbe" font-family="sans-serif" font-size="12">'
           'SYNTHETIC BENCHMARK · no live market data · no orders</text>'
           f'{grid}{"".join(candles)}'
           f'<polyline id="close-series" points="{" ".join(points)}" fill="none" '
           'stroke="#3bcfff" stroke-width="2" opacity="0.65"/>'
           '<text x="65" y="357" fill="#91acbe" font-family="sans-serif" font-size="13">09:30</text>'
           '<text x="780" y="357" fill="#91acbe" font-family="sans-serif" font-size="13">09:37</text>'
           '<text x="40" y="394" fill="#a6bfce" font-family="sans-serif" font-size="13">'
           '8 deterministic candles · evidence checked independently · local SVG artifact</text></svg>')
    return svg.encode("utf-8")


def execute(persona_key: str, source: dict, *, upstream: dict | None = None) -> tuple[dict, bytes | None]:
    """Produce an output. Only the separate verifier may mark it accepted."""
    base = {"schema_version": 1, "source": "synthetic", "executor": EXECUTOR,
            "fixture_id": source["fixture_id"], "input_sha256": digest(json_bytes(source))}
    if persona_key == "marina":
        ledger = source["ledger"]
        gross, fees = sum(ledger["gross_cents"]), sum(ledger["fees_cents"])
        return {**base, "gross_cents": gross, "fees_cents": fees, "net_cents": gross - fees,
                "closing_cents": ledger["initial_cents"] + gross - fees,
                "entry_count": len(ledger["gross_cents"])}, None
    if persona_key == "tolik":
        closes = [bar["close_ticks"] for bar in source["bars"]]
        return {**base, "sample_count": len(closes), "sum_ticks": sum(closes),
                "mean_tick_x100": sum(closes) * 100 // len(closes),
                "minimum_ticks": min(closes), "maximum_ticks": max(closes),
                "delta_ticks": closes[-1] - closes[0]}, None
    if persona_key == "nikita":
        priorities = [{"id": row["id"], "priority": "review" if row["severity"] >= 3
                       else "scheduled" if row["scheduled"] else "information"}
                      for row in source["events"]]
        return {**base, "events": priorities, "review_count": sum(
            item["priority"] == "review" for item in priorities)}, None
    if persona_key == "ivan":
        if not upstream or upstream.get("input_sha256") != base["input_sha256"]:
            raise ContractError("verified_upstream_required")
        svg = build_chart(source)
        return {**base, "chart_sha256": digest(svg), "bar_count": len(source["bars"]),
                "width": 960, "height": 420, "upstream_sha256": digest(json_bytes(upstream))}, svg
    raise ContractError("unknown_demo_persona")
