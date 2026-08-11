from __future__ import annotations

from app import governance, integrations


def test_document_owner_is_explicit_and_consistent() -> None:
    assert governance.PROJECT_OWNER == "Черевко Дмитро"
    documents = governance.list_documents()
    assert documents
    assert all(row["owner"] == governance.PROJECT_OWNER for row in documents)


def test_integration_status_never_exposes_secrets(monkeypatch) -> None:
    integrations.market_data_failover.TopstepXProvider._adapter_instance = None
    integrations.market_data_failover.TopstepXProvider._credential_fingerprint = ""
    monkeypatch.setattr(integrations.market_data_live_adapters.secure_store, "available", lambda: False)
    for name in (
        "NTA_TOPSTEPX_USERNAME", "NTA_TOPSTEPX_API_KEY",
        "NTA_ENABLE_TOPSTEPX_MARKET_DATA", "NTA_ENABLE_TOPSTEPX_LIVE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NTA_TELEGRAM_BOT_TOKEN", "secret-telegram-token")
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "123456")
    # Legacy account/key variables cannot configure the ProjectX read-only
    # feed: it needs an explicit TopstepX username plus API key.  Keeping this
    # test honest prevents a status UI from claiming an unauthorized provider.
    monkeypatch.setenv("NTA_TOPSTEP_API_KEY", "secret-topstep-key")
    monkeypatch.setenv("NTA_TOPSTEP_ACCOUNT_ID", "account-1")
    status = integrations.status()
    assert status["telegram"]["configured"] is True
    assert status["topstep"]["configured"] is False
    assert status["topstep"]["live_actions_enabled"] is False
    assert status["topstep"]["available"] is False
    assert status["topstep"]["phase"] == "read_only_market_data"
    assert status["topstep"]["blocking_reasons"]
    assert "secret" not in str(status).lower()
    assert "123456" not in str(status)


def test_unconfigured_news_is_honest_and_empty(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("NTA_NEWS_FEEDS", raising=False)
    monkeypatch.setattr(integrations, "_root", lambda: tmp_path)
    result = integrations.news()
    assert result["configured"] is False
    assert result["items"] == []
