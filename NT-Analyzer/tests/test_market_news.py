from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app import integrations, market_news

_RSS = """<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0'><channel>
  <item><title>CPI rises in latest inflation report</title>
    <link>https://www.bls.gov/cpi.htm</link>
    <description>Consumer price index update.</description>
    <pubDate>Mon, 29 Jun 2026 12:30:00 GMT</pubDate></item>
  <item><title>Library hours notice</title>
    <link>https://example.gov/notice.htm</link>
    <description>Unrelated administrative note.</description>
    <pubDate>Mon, 29 Jun 2026 09:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_classify_tags_high_impact_macro() -> None:
    sev, instruments = market_news._classify("FOMC raises the federal funds rate", "")
    assert sev == "high"
    assert "MES" in instruments
    assert market_news._classify("Local park reopening", "")[0] == "low"
    assert market_news._classify("Emergency trading halt after bank failure", "")[0] == "high"
    assert market_news._classify("New tariff and sanctions announced", "")[0] == "medium"


def test_parse_feed_extracts_items_and_severity() -> None:
    items = market_news._parse_feed("BLS", _RSS.encode("utf-8"), "2026-06-29T13:00:00Z")
    assert len(items) == 2
    cpi = items[0]
    assert cpi["item_type"] == "live_news"
    assert cpi["source_type"] == "rss"
    assert cpi["severity"] == "high"
    assert cpi["source_url"].startswith("https://")
    assert cpi["published_at_utc"] == "2026-06-29T12:30:00Z"


def test_feeds_env_override(monkeypatch) -> None:
    monkeypatch.setenv("NTA_NEWS_LIVE_FEEDS", "Fed|https://example.gov/a.xml, https://example.gov/b.xml")
    feeds = market_news._feeds()
    assert ("Fed", "https://example.gov/a.xml") in feeds
    assert any(url == "https://example.gov/b.xml" for _, url in feeds)


def test_alpha_vantage_rate_limit_is_sanitized(monkeypatch) -> None:
    api_key = "5E84M75TLHE42OTD"
    monkeypatch.setenv("NTA_ALPHAVANTAGE_API_KEY", api_key)
    payload = {
        "Note": f"We have detected your API key as {api_key} and our standard API rate limit is 25 requests per day.",
    }
    monkeypatch.setattr(market_news, "_http_get", lambda url, accept="application/json": json.dumps(payload).encode("utf-8"))

    items, status = market_news._alpha_vantage("2026-06-30T03:00:00Z", {})
    assert items == []
    assert status["ok"] is False
    assert "дневной лимит" in status["error"]
    assert api_key not in status["error"]
    assert status["fetched_at_utc"] == "2026-06-30T03:00:00Z"


def test_alpha_vantage_reuses_cached_result_inside_min_interval(monkeypatch) -> None:
    monkeypatch.setenv("NTA_ALPHAVANTAGE_API_KEY", "DEMOALPHATESTKEY")
    cached_doc = {
        "providers": [{
            "name": "Alpha Vantage · News",
            "ok": True,
            "count": 1,
            "error": "",
            "source_type": "api",
            "fetched_at_utc": "2026-06-30T02:00:00Z",
        }],
        "items": [{
            "title": "Macro headline",
            "source": "Alpha Vantage",
            "severity": "high",
            "published_at_utc": "2026-06-30T01:45:00Z",
        }],
    }

    def _boom(url, accept="application/json"):
        raise AssertionError("network should not be used when cached Alpha result is still fresh")

    monkeypatch.setattr(market_news, "_http_get", _boom)
    items, status = market_news._alpha_vantage("2026-06-30T03:00:00Z", cached_doc)
    assert len(items) == 1
    assert items[0]["source"] == "Alpha Vantage"
    assert status["cached"] is True
    assert status["name"] == "Alpha Vantage · News"


def test_fetch_live_news_degrades_without_network(monkeypatch) -> None:
    monkeypatch.setattr(market_news, "_feeds", lambda: [("Fed", "https://example.gov/x.xml")])
    monkeypatch.delenv("NTA_ALPHAVANTAGE_API_KEY", raising=False)

    def _boom(url):
        raise OSError("offline")

    monkeypatch.setattr(market_news, "_http_get", _boom)
    doc = market_news.fetch_live_news()
    assert doc["items"] == []
    assert any(p["name"] == "Fed" and not p["ok"] for p in doc["providers"])
    assert all("offline" in p["error"] or "ключ" in p["error"] for p in doc["providers"] if not p["ok"])


def test_integrations_live_news_filters_recent(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(integrations, "_root", lambda: tmp_path)
    monkeypatch.delenv("NTA_NEWS_LIVE_FEEDS", raising=False)
    now = datetime.now(timezone.utc)
    fresh = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stale = (now - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {
        "generated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "providers": [{"name": "BLS", "ok": True, "count": 2, "error": "", "source_type": "rss"}],
        "items": [
            {"title": "Fresh CPI headline", "source": "BLS", "severity": "high", "published_at_utc": fresh, "source_url": "https://bls.gov/x"},
            {"title": "Old headline", "source": "BLS", "severity": "low", "published_at_utc": stale},
        ],
    }
    target = tmp_path / "data" / "integrations" / "live_news.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(doc), encoding="utf-8")

    result = integrations.live_news(max_age_min=60, limit=40)
    assert result["configured"] is True
    assert result["total_recent"] == 1
    assert result["items"][0]["title"] == "Fresh CPI headline"
    assert result["items"][0]["item_type"] == "live_news"
    assert result["providers_ok"] == 1


def test_integrations_live_news_unconfigured_is_honest(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(integrations, "_root", lambda: tmp_path)
    monkeypatch.delenv("NTA_NEWS_LIVE_FEEDS", raising=False)
    result = integrations.live_news()
    assert result["configured"] is False
    assert result["items"] == []
    assert "не настроена" in result["note"]
