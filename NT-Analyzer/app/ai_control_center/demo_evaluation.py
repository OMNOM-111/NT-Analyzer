"""Evidence verifier for a fixed synthetic benchmark, independent of executors.

This measures fixture acceptance only. It is not a model reputation, market
backtest, human acceptance, calibrated quality score or routing signal.
"""
from __future__ import annotations

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from collections import Counter


def _hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_integer(value: object) -> bool:
    return type(value) is int


def _chart_check(source: dict, output: dict, svg: bytes | None, upstream: dict | None) -> bool:
    if not isinstance(svg, bytes) or len(svg) > 262144 or not upstream:
        return False
    if hashlib.sha256(svg).hexdigest() != output.get("chart_sha256"):
        return False
    if output.get("upstream_sha256") != _hash(upstream):
        return False
    # Never interpret DTDs/entities and never trust scripts, external URLs or HTML.
    lowered = svg.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        return False
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return False
    if (root.tag != "{http://www.w3.org/2000/svg}svg" or root.get("width") != "960"
            or root.get("height") != "420" or root.get("viewBox") != "0 0 960 420"
            or output.get("width") != 960 or output.get("height") != 420):
        return False
    allowed_tags = {"svg", "title", "rect", "text", "line", "g", "polyline"}
    points = None
    candles = []
    for item in root.iter():
        if item.tag.removeprefix("{http://www.w3.org/2000/svg}") not in allowed_tags:
            return False
        if any(key.lower().startswith("on") or "href" in key.lower() or "url(" in value.lower()
               for key, value in item.attrib.items()):
            return False
        if item.get("class") == "candle":
            candles.append(item)
        if item.get("id") == "close-series":
            if points is not None:
                return False
            points = item.get("points", "")
    bars = source["bars"]
    if len(candles) != len(bars) or output.get("bar_count") != len(bars) or not points:
        return False
    try:
        coordinates = [tuple(map(float, point.split(","))) for point in points.split()]
        low = min(row["low_ticks"] for row in bars) - 2
        span = max(row["high_ticks"] for row in bars) + 2 - low
        for index, (group, bar) in enumerate(zip(candles, bars)):
            children = list(group)
            if [node.tag for node in children] != ["{http://www.w3.org/2000/svg}line",
                                                  "{http://www.w3.org/2000/svg}rect"]:
                return False
            line, body = children
            y = lambda ticks: 330 - (ticks - low) * 250 / span
            expected = ((line, "x1", 100 + index * 100), (line, "x2", 100 + index * 100),
                        (line, "y1", y(bar["high_ticks"])), (line, "y2", y(bar["low_ticks"])),
                        (body, "x", 88 + index * 100), (body, "width", 24),
                        (body, "y", min(y(bar["open_ticks"]), y(bar["close_ticks"]))),
                        (body, "height", max(abs(y(bar["open_ticks"]) - y(bar["close_ticks"])), 2)))
            for node, attribute, value in expected:
                actual = float(node.get(attribute, "nan"))
                if not math.isfinite(actual) or abs(actual - value) >= 0.011:
                    return False
        return (len(coordinates) == len(bars) and all(len(p) == 2 and all(math.isfinite(v) for v in p)
                and abs(p[0] - (100 + index * 100)) < 0.01
                and abs(p[1] - (330 - (bars[index]["close_ticks"] - low) * 250 / span)) < 0.011
                for index, p in enumerate(coordinates)))
    except (ValueError, TypeError, ZeroDivisionError):
        return False


def evaluate(persona_key: str, source: dict, output: dict, *, svg: bytes | None = None,
             upstream: dict | None = None) -> dict:
    """Recompute expectations from evidence, never call the executor to grade it."""
    common = (output.get("source") == source.get("source") == "synthetic"
              and output.get("executor") == "local_deterministic"
              and type(output.get("schema_version")) is int and output.get("schema_version") == 1
              and output.get("fixture_id") == source.get("fixture_id"))
    integrity = output.get("input_sha256") == _hash(source)
    correctness = False
    structure = False
    if persona_key == "marina":
        journal = source["ledger"]
        debit, credit = 0, 0
        for amount in journal["gross_cents"]:
            credit += amount
        for amount in journal["fees_cents"]:
            debit += amount
        expected = {"gross_cents": credit, "fees_cents": debit, "net_cents": credit - debit,
                    "closing_cents": journal["initial_cents"] + credit - debit,
                    "entry_count": len(journal["gross_cents"])}
        structure = all(_is_integer(output.get(key)) for key in expected)
        correctness = all(output.get(key) == value for key, value in expected.items())
    elif persona_key == "tolik":
        frequencies = Counter(row["close_ticks"] for row in source["bars"])
        size = sum(frequencies.values())
        total = sum(price * count for price, count in frequencies.items())
        expected = {"sample_count": size, "sum_ticks": total, "mean_tick_x100": total * 100 // size,
                    "minimum_ticks": sorted(frequencies)[0], "maximum_ticks": sorted(frequencies)[-1],
                    "delta_ticks": source["bars"][-1]["close_ticks"] - source["bars"][0]["close_ticks"]}
        structure = all(_is_integer(output.get(key)) for key in expected)
        correctness = all(output.get(key) == value for key, value in expected.items())
    elif persona_key == "nikita":
        expected = []
        for item in source["events"]:
            label = {1: "scheduled" if item["scheduled"] else "information",
                     2: "scheduled" if item["scheduled"] else "information", 3: "review", 4: "review"}[item["severity"]]
            expected.append({"id": item["id"], "priority": label})
        structure = isinstance(output.get("events"), list) and _is_integer(output.get("review_count"))
        correctness = output.get("events") == expected and output.get("review_count") == len(
            [row for row in expected if row["priority"] == "review"])
    elif persona_key == "ivan":
        structure = all(_is_integer(output.get(key)) for key in ("bar_count", "width", "height"))
        correctness = _chart_check(source, output, svg, upstream)
    rubric = [{"key": key, "passed": bool(passed)} for key, passed in (
        ("synthetic_provenance", common), ("input_integrity", integrity),
        ("output_contract", structure), ("independent_recomputation", correctness))]
    passed_count = sum(item["passed"] for item in rubric)
    return {"schema_version": 1, "source": "synthetic", "mode": "deterministic_synthetic",
            "scope": "fixed_synthetic_benchmark", "verifier": "independent_deterministic_checker",
            "verifier_version": "1", "fixture_id": source["fixture_id"], "persona_key": persona_key,
            "input_sha256": _hash(source), "output_sha256": _hash(output),
            "passed": passed_count == len(rubric), "score_pct": passed_count * 100 // len(rubric),
            "rubric": rubric, "routing_effect": "none", "model_quality_assessed": False}
