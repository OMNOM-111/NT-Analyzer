"""Live / recent market-news fetchers (modular, offline-safe).

This is the *news* layer, distinct from the scheduled economic calendar in
:mod:`app.market_events`. It pulls recent headlines from free official RSS
feeds (Federal Reserve, BLS, BEA, EIA) and optionally from free-tier APIs
(Alpha Vantage). Every provider is independent: a failing or unreachable
source never breaks the others, and each run records a status row
(last fetch time, item count, error) so the UI can show fetcher health.

Network is optional. With no internet (or all feeds blocked) the result is an
honest empty feed plus per-provider error statuses — never fake headlines.

Nothing here is wired to trade execution; this is informational only.
"""
from __future__ import annotations

import json
import html
import os
import re
from concurrent.futures import ThreadPoolExecutor
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple
from xml.etree import ElementTree as ET

from app import local_secrets, runtime_env

local_secrets.apply()

_UA = "NT-Analyzer/1.0 (+local; market-news-fetch)"
_MAX_BYTES = 3_000_000
_TIMEOUT = 8
_ALPHA_MIN_INTERVAL_MIN = 75

# Default free, official RSS feeds. Operators can override / extend with the
# NTA_NEWS_LIVE_FEEDS env var: "Label|https://url, Label2|https://url2".
DEFAULT_FEEDS: List[Tuple[str, str]] = [
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("Federal Reserve · speeches", "https://www.federalreserve.gov/feeds/speeches.xml"),
    ("BLS", "https://www.bls.gov/feed/bls_latest.rss"),
    ("BEA", "https://apps.bea.gov/rss/rss.xml"),
    ("EIA · Today in Energy", "https://www.eia.gov/rss/todayinenergy.xml"),
    ("U.S. Department of Labor", "https://www.dol.gov/rss/releases.xml"),
]

# General-agency feeds contain large amounts of operational news.  Keep only
# market-classified rows from these sources so the trading ticker is not
# crowded by unrelated enforcement or administrative headlines.
_RELEVANT_ONLY_SOURCES = {"U.S. Department of Labor"}

# Keyword → (severity, affected instruments). First match wins (high first).
_RULES: List[Tuple[re.Pattern, str, List[str]]] = [
    (re.compile(r"\b(emergency (rate|meeting|facility)|unscheduled (rate|fomc)|bank failure|bank run|default|circuit breaker|trading halt|market closure)\b", re.I),
     "high", ["MNQ", "MES", "MYM", "MGC", "MCL", "USD"]),
    (re.compile(r"\b(fomc|federal funds|rate decision|interest rate|monetary policy)\b", re.I),
     "high", ["MNQ", "MES", "MYM", "MGC", "MCL", "USD"]),
    (re.compile(r"\b(powell|chair\b|testimony|press conference)\b", re.I),
     "high", ["MNQ", "MES", "MGC", "USD"]),
    (re.compile(r"\b(cpi|inflation|consumer price|ppi|producer price|pce)\b", re.I),
     "high", ["MNQ", "MES", "MYM", "MGC", "USD"]),
    (re.compile(r"\b(payroll|employment situation|nonfarm|nfp|unemployment|jobless|jolts)\b", re.I),
     "high", ["MNQ", "MES", "MYM", "MGC", "USD"]),
    (re.compile(r"\b(retail sales|durable goods|consumer confidence|ism|pmi)\b", re.I),
     "high", ["MNQ", "MES", "MYM", "MGC", "USD"]),
    (re.compile(r"\b(gdp|gross domestic|growth estimate)\b", re.I),
     "medium", ["MNQ", "MES", "MYM"]),
    (re.compile(r"\b(petroleum|crude|oil|gasoline|inventor|eia)\b", re.I),
     "medium", ["MCL", "CL", "MGC"]),
    (re.compile(r"\b(speech|remarks|statement|beige book|minutes)\b", re.I),
     "medium", ["MNQ", "MES", "MGC", "USD"]),
    (re.compile(r"\b(tariff|sanction|geopolitical|ceasefire|shipping disruption)\b", re.I),
     "medium", ["MNQ", "MES", "MGC", "MCL", "USD"]),
]


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _live_news_path() -> Path:
    return runtime_env.data_path(
        "integrations", "live_news.json", project_root=_root(),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _classify(title: str, summary: str) -> Tuple[str, List[str]]:
    text = f"{title} {summary}"
    for pattern, severity, instruments in _RULES:
        if pattern.search(text):
            return severity, instruments
    return "low", []


def _read_cached_live_doc() -> Dict[str, Any]:
    path = _live_news_path()
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _parse_iso(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _minutes_between(older: str, newer: str) -> float | None:
    old_dt = _parse_iso(older)
    new_dt = _parse_iso(newer)
    if old_dt is None or new_dt is None:
        return None
    return (new_dt - old_dt).total_seconds() / 60.0


def _cached_provider(doc: Dict[str, Any], name: str) -> Dict[str, Any] | None:
    providers = doc.get("providers")
    if not isinstance(providers, list):
        return None
    for row in providers:
        if isinstance(row, dict) and str(row.get("name") or "") == name:
            return dict(row)
    return None


def _cached_alpha_items(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = doc.get("items")
    if not isinstance(rows, list):
        return []
    cached = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source") or "")
        if source.lower().startswith("alpha vantage"):
            cached.append(dict(row))
    return cached


def _sanitize_alpha_error(message: str) -> str:
    text = _strip_html(str(message or "").strip()) or "ошибка API"
    masked = re.sub(r"\b[A-Z0-9]{12,}\b", "********", text)
    lower = masked.lower()
    if "25 requests per day" in lower or "premium plans" in lower or "rate limit" in lower:
        return "дневной лимит Alpha Vantage исчерпан (free-tier 25 запросов/день)"
    if "api key" in lower:
        return "Alpha Vantage отклонил API-ключ"
    return masked[:200]


def _feeds() -> List[Tuple[str, str]]:
    raw = os.environ.get("NTA_NEWS_LIVE_FEEDS", "").strip()
    if not raw:
        return list(DEFAULT_FEEDS)
    feeds: List[Tuple[str, str]] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        label, _, url = chunk.partition("|")
        url = (url or label).strip()
        label = label.strip() if url != label else "feed"
        if url.startswith(("https://", "http://")):
            feeds.append((label, url))
    return feeds or list(DEFAULT_FEEDS)


def _http_get(url: str, *, accept: str = "application/rss+xml, application/xml, text/xml") -> bytes:
    if not url.startswith(("https://", "http://")):
        raise ValueError("only http(s) URLs are allowed")
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 - fixed official feeds, https only
        return resp.read(_MAX_BYTES)


def _text(node) -> str:
    return (node.text or "").strip() if node is not None else ""


def _strip_html(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


_IMG_SRC_RE = re.compile(r"""<img[^>]+src=["']([^"']+)["']""", re.I)


def _normalize_image_url(value: str) -> str:
    url = html.unescape(str(value or "").strip())
    if url.startswith("//"):
        url = "https:" + url
    return url if url.startswith(("https://", "http://")) else ""


def _extract_image_url_from_html(value: str) -> str:
    raw = html.unescape(value or "")
    match = _IMG_SRC_RE.search(raw)
    return _normalize_image_url(match.group(1)) if match else ""


def _element_htmlish(node) -> str:
    if node is None:
        return ""
    parts = [node.text or ""]
    for child in node:
        parts.append(ET.tostring(child, encoding="unicode", method="html"))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _node_image_url(node, *, is_atom: bool) -> str:
    for child in node.iter():
        local = child.tag.split("}")[-1].lower()
        if local == "enclosure":
            url = _normalize_image_url(child.get("url") or "")
            media_type = str(child.get("type") or "").lower()
            if url and (not media_type or media_type.startswith("image/")):
                return url
        if local == "thumbnail":
            url = _normalize_image_url(child.get("url") or "")
            if url:
                return url
        if local == "content":
            url = _normalize_image_url(child.get("url") or "")
            medium = str(child.get("medium") or "").lower()
            media_type = str(child.get("type") or "").lower()
            if url and (medium == "image" or media_type.startswith("image/")):
                return url
    if is_atom:
        raw = _element_htmlish(node.find("{*}summary")) or _element_htmlish(node.find("summary"))
        raw = raw or _element_htmlish(node.find("{*}content")) or _element_htmlish(node.find("content"))
    else:
        raw = _element_htmlish(node.find("description"))
    return _extract_image_url_from_html(raw)


def _parse_published(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        pass
    try:  # ISO-8601 (Atom <updated>)
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return ""


def _parse_feed(source: str, xml_bytes: bytes, fetched_at: str) -> List[Dict[str, Any]]:
    root = ET.fromstring(xml_bytes)
    tag = root.tag.lower()
    items: List[Dict[str, Any]] = []
    # RSS 2.0: channel/item ; Atom: feed/entry
    nodes = root.findall(".//item")
    is_atom = False
    if not nodes:
        nodes = [n for n in root.iter() if n.tag.lower().endswith("}entry") or n.tag.lower() == "entry"]
        is_atom = True
    for node in nodes:
        if is_atom:
            title = _text(node.find("{*}title")) or _text(node.find("title"))
            link_node = node.find("{*}link")
            link = (link_node.get("href") if link_node is not None else "") or ""
            published = _parse_published(_text(node.find("{*}updated")) or _text(node.find("{*}published")))
            summary = _strip_html(_text(node.find("{*}summary")) or _text(node.find("{*}content")))
        else:
            title = _text(node.find("title"))
            link = _text(node.find("link"))
            published = _parse_published(_text(node.find("pubDate")) or _text(node.find("{*}date")))
            summary = _strip_html(_text(node.find("description")))
        title = _strip_html(title)
        if not title:
            continue
        severity, instruments = _classify(title, summary)
        link = link if link.startswith(("https://", "http://")) else ""
        image_url = _node_image_url(node, is_atom=is_atom)
        items.append({
            "id": f"live:{source}:{published or title[:48]}",
            "item_type": "live_news",
            "title": title,
            "summary": summary[:280],
            "image_url": image_url,
            "source": source,
            "source_type": "rss",
            "source_url": link,
            "url": link,
            "severity": severity,
            "impact": severity,
            "category": "live",
            "affected_instruments": instruments,
            "instruments": instruments,
            "published_at_utc": published,
            "event_time_utc": published,
            "fetched_at_utc": fetched_at,
            "is_confirmed": True,
        })
    return items


def _alpha_vantage(fetched_at: str, cached_doc: Dict[str, Any] | None = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    key = os.environ.get("NTA_ALPHAVANTAGE_API_KEY", "").strip()
    name = "Alpha Vantage · News"
    if not key:
        return [], {"name": name, "ok": False, "count": 0, "error": "ключ не задан (NTA_ALPHAVANTAGE_API_KEY)", "source_type": "api", "fetched_at_utc": fetched_at}
    cached_doc = cached_doc or {}
    min_interval = max(30, int(os.environ.get("NTA_ALPHAVANTAGE_MIN_INTERVAL_MIN", str(_ALPHA_MIN_INTERVAL_MIN)) or _ALPHA_MIN_INTERVAL_MIN))
    cached_status = _cached_provider(cached_doc, name)
    cached_items = _cached_alpha_items(cached_doc)
    if cached_status:
        minutes_since = _minutes_between(str(cached_status.get("fetched_at_utc") or ""), fetched_at)
        if minutes_since is not None and minutes_since < min_interval:
            status = dict(cached_status)
            status["cached"] = True
            status["source_type"] = "api"
            return cached_items, status
    url = ("https://www.alphavantage.co/query?function=NEWS_SENTIMENT"
           "&topics=economy_macro&sort=LATEST&limit=50&apikey=" + urllib.parse.quote(key))
    try:
        doc = json.loads(_http_get(url, accept="application/json").decode("utf-8", "replace"))
    except (urllib.error.URLError, ValueError, OSError, TimeoutError) as exc:
        return [], {"name": name, "ok": False, "count": 0, "error": _sanitize_alpha_error(str(exc)), "source_type": "api", "fetched_at_utc": fetched_at}
    if not isinstance(doc, dict):
        return [], {"name": name, "ok": False, "count": 0, "error": "некорректный ответ API", "source_type": "api", "fetched_at_utc": fetched_at}
    if doc.get("Error Message") or doc.get("Information") or doc.get("Note"):
        err = _sanitize_alpha_error(str(doc.get("Error Message") or doc.get("Information") or doc.get("Note") or "ошибка API"))
        return [], {"name": name, "ok": False, "count": 0, "error": err, "source_type": "api", "fetched_at_utc": fetched_at}
    items: List[Dict[str, Any]] = []
    for row in doc.get("feed", []) if isinstance(doc, dict) else []:
        title = _strip_html(str(row.get("title") or ""))
        if not title:
            continue
        published = _parse_published(_format_av_time(str(row.get("time_published") or "")))
        summary = _strip_html(str(row.get("summary") or ""))
        # Alpha Vantage's economy topic often includes single-stock articles
        # whose summaries merely mention rates, labor or oil. Classifying on
        # the headline prevents incidental words from producing false red
        # macro alerts.
        severity, instruments = _classify(title, "")
        link = str(row.get("url") or "")
        link = link if link.startswith(("https://", "http://")) else ""
        image_url = _normalize_image_url(str(row.get("banner_image") or ""))
        items.append({
            "id": f"live:av:{row.get('url') or title[:48]}",
            "item_type": "live_news", "title": title, "summary": summary[:280],
            "image_url": image_url,
            "source": str(row.get("source") or "Alpha Vantage"), "source_type": "api",
            "source_url": link, "url": link, "severity": severity, "impact": severity,
            "category": "live", "affected_instruments": instruments, "instruments": instruments,
            "published_at_utc": published, "event_time_utc": published,
            "fetched_at_utc": fetched_at, "is_confirmed": True,
        })
    return items, {"name": name, "ok": True, "count": len(items), "error": "", "source_type": "api", "fetched_at_utc": fetched_at}


def _format_av_time(value: str) -> str:
    # Alpha Vantage uses YYYYMMDDTHHMMSS
    if re.fullmatch(r"\d{8}T\d{6}", value or ""):
        return f"{value[0:4]}-{value[4:6]}-{value[6:8]}T{value[9:11]}:{value[11:13]}:{value[13:15]}Z"
    return value


def fetch_live_news() -> Dict[str, Any]:
    """Fetch all providers; return {items, providers, generated_at_utc}."""
    fetched_at = _now().strftime("%Y-%m-%dT%H:%M:%SZ")
    items: List[Dict[str, Any]] = []
    providers: List[Dict[str, Any]] = []
    cached_doc = _read_cached_live_doc()
    def fetch_feed(feed: Tuple[str, str]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        label, url = feed
        try:
            parsed = _parse_feed(label, _http_get(url), fetched_at)
            if label in _RELEVANT_ONLY_SOURCES:
                parsed = [item for item in parsed if item.get("severity") != "low"]
            return parsed, {"name": label, "ok": True, "count": len(parsed), "error": "", "source_type": "rss", "fetched_at_utc": fetched_at, "url": url}
        except (urllib.error.URLError, ET.ParseError, ValueError, OSError, TimeoutError) as exc:
            return [], {"name": label, "ok": False, "count": 0, "error": str(exc)[:200], "source_type": "rss", "fetched_at_utc": None, "url": url}

    feeds = _feeds()
    # Providers are independent and network latency should not add up during a
    # refresh.  The bounded pool keeps startup refresh comfortably in the
    # background even when several government sites are slow.
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(feeds)))) as pool:
        for parsed, status in pool.map(fetch_feed, feeds):
            items.extend(parsed)
            providers.append(status)
    av_items, av_status = _alpha_vantage(fetched_at, cached_doc)
    items.extend(av_items)
    providers.append(av_status)

    seen, deduped = set(), []
    for item in sorted(items, key=lambda i: str(i.get("published_at_utc") or ""), reverse=True):
        key = (item.get("title"), item.get("source"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return {"generated_at_utc": fetched_at, "items": deduped, "providers": providers}


def write_live_news() -> Path:
    path = _live_news_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(fetch_live_news(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


if __name__ == "__main__":
    written = write_live_news()
    doc = json.loads(written.read_text(encoding="utf-8"))
    ok = sum(1 for p in doc["providers"] if p.get("ok"))
    print(f"wrote {written}")
    print(f"providers ok: {ok}/{len(doc['providers'])} · items: {len(doc['items'])}")
    for prov in doc["providers"]:
        flag = "OK " if prov.get("ok") else "ERR"
        print(f"  [{flag}] {prov['name']}: {prov.get('count', 0)} {prov.get('error', '')}".rstrip())
