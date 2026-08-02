from __future__ import annotations

from app.ai_lab import news_agent


def _item(item_id: str, title: str, severity: str = "high"):
    return {
        "id": item_id, "title": title, "summary": "Official release summary",
        "source": "BLS", "source_type": "rss", "source_url": "https://www.bls.gov/",
        "severity": severity, "affected_instruments": ["MNQ", "MES"],
        "image_url": "https://www.eia.gov/images/chart.png",
        "published_at_utc": "2026-07-02T18:00:00Z", "age_min": 5, "is_confirmed": True,
    }


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(news_agent, "_state_path", lambda: tmp_path / "news-agent.json")
    monkeypatch.setattr(news_agent.runtime, "read_strategies_raw", lambda: [
        {"enabled": True, "strategy_id": "S1", "strategy_class": "Alpha", "instrument": "MNQ 09-26", "account_name": "SIM"},
    ])


def test_initial_news_baseline_uses_no_model_or_telegram(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(news_agent.agent_router, "invoke_role", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM must not run for baseline")))
    monkeypatch.setattr(news_agent, "_notify_telegram", lambda record: (_ for _ in ()).throw(AssertionError("Telegram must not run for baseline")))

    out = news_agent.observe_items([_item("N1", "Employment Situation")])

    assert out["baseline"] is True
    assert out["added"] == 1
    assert out["alerts_sent"] == 0


def test_new_high_news_gets_one_model_analysis_and_alert(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    news_agent.observe_items([_item("N1", "Existing headline")], send_telegram=False, use_llm=False)
    calls = []
    monkeypatch.setattr(news_agent.agent_router, "invoke_role", lambda *args, **kwargs: calls.append(kwargs) or {
        "content": "Факт: релиз способен повысить волатильность.\nРекомендация: проверить защитные окна.",
        "actual_model": "deepseek-test", "provider": "deepseek", "cost_usd": 0.001,
    })
    monkeypatch.setattr(news_agent, "_notify_telegram", lambda record: True)

    first = news_agent.observe_items([_item("N2", "New emergency release")])
    duplicate = news_agent.observe_items([_item("N2", "New emergency release")])

    assert first["added"] == 1 and first["alerts_sent"] == 1
    assert duplicate["added"] == 0
    assert len(calls) == 1
    saved = next(row for row in news_agent._read()["analyses"] if row["news_id"] == "N2")
    assert saved["model"] == "deepseek-test"
    assert saved["telegram_sent"] is True


def test_snapshot_combines_released_and_upcoming_without_llm(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(news_agent.integrations, "live_news", lambda **kwargs: {"all_items": [_item("N1", "Released CPI")]})
    monkeypatch.setattr(news_agent.integrations, "news", lambda limit=200: {"items": []})

    out = news_agent.snapshot()

    assert out["agent"]["name"] == "Никита"
    assert out["summary"]["high"] == 1
    assert out["items"][0]["recommendation"]
    assert out["items"][0]["summary_ru"].startswith("BLS опубликовал релиз")
    assert out["items"][0]["short_recommendation"]
    assert out["items"][0]["relevance_until_utc"]
    assert out["items"][0]["image_url"] == "https://www.eia.gov/images/chart.png"
    assert out["items"][0]["internet_context"]["method"] == "official_feed_summary_and_source_link"


def test_old_headline_new_to_cache_is_reported_but_not_alerted(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    news_agent.observe_items([_item("N1", "Baseline")], send_telegram=False, use_llm=False)
    old = _item("N-OLD", "Old high-impact release")
    old["age_min"] = 600
    monkeypatch.setattr(news_agent.agent_router, "invoke_role", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("old item must not call LLM")))
    monkeypatch.setattr(news_agent, "_notify_telegram", lambda record: (_ for _ in ()).throw(AssertionError("old item must not alert")))

    out = news_agent.observe_items([old])

    assert out["added"] == 1
    assert out["alerts_sent"] == 0


def test_medium_news_never_uses_llm_or_alerts(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    news_agent.observe_items([_item("N1", "Baseline")], send_telegram=False, use_llm=False)
    medium = _item("N-MED", "Medium release", severity="medium")
    monkeypatch.setattr(news_agent.agent_router, "invoke_role", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("medium item must not call LLM")))
    monkeypatch.setattr(news_agent, "_notify_telegram", lambda record: (_ for _ in ()).throw(AssertionError("medium item must not alert")))

    out = news_agent.observe_items([medium])

    assert out["added"] == 1
    assert out["alerts_sent"] == 0
