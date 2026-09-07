"""Read-time result rendering: no browser, credentials, network or history writes."""
from __future__ import annotations

import copy
import json
import subprocess

import pytest

from tests.test_agent_world_ui import AURORA, ARTIFACT, ROOT, SCRIPT, evaluate


def chat_render(row):
    source = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    # The slice has to cover everything the rendered functions call. Integration
    # added orchAgentWorldTaskId/Views/Card just above orchAgentWorldReportUrl,
    # and the message renderer calls them, so the window starts there now.
    helpers = "function orchAgentWorldTaskId(" + source.split("function orchAgentWorldTaskId(", 1)[1].split("function orchChainHtml(", 1)[0]
    message = "function orchMessageHtml(" + source.split("function orchMessageHtml(", 1)[1].split("function orchStopFeedbackVoice(", 1)[0]
    script = ("const esc=require(" + json.dumps(str(SCRIPT)) + ").esc;"
        "const ORCH_ACTION_LABELS={}, ORCH_ACTION_STATES={completed:['','done']},ORCH={};"
        "const orchFmtTime=()=>'',orchFooterHtml=()=>'',agentAvatarHtml=()=>'',orchAwaitHtml=()=>'';"
        + helpers + message + "const row=" + json.dumps(row) + ";"
        "const before=JSON.stringify(row); const html=orchMessageHtml(row);"
        "process.stdout.write(JSON.stringify({html,url:orchAgentWorldReportUrl(row),unchanged:before===JSON.stringify(row)}));")
    result = subprocess.run(["node", "-e", script], cwd=ROOT, check=True, capture_output=True,
                            text=True, encoding="utf-8", timeout=20)
    return json.loads(result.stdout)


def report_message():
    return {"role": "assistant", "source": "agent_world_local", "content": "64 trades, net -969.7",
            "actions": [{"source_kind": "real_model_response", "name": "real_model_response", "status": "completed",
                         "synthetic": False, "verification": {"passed": True}, "source_job_id": "awnt_123",
                         "report_url": "/ui/backtesting.html?job=awnt_123"}],
            "attachments": [{"type": "image", "url": ARTIFACT, "caption": ""}]}


@pytest.mark.parametrize("attachment_type", ["image", "artifact"])
def test_historical_and_new_report_files_are_links_not_broken_images(attachment_type):
    row = report_message()
    row["attachments"][0]["type"] = attachment_type
    rendered = chat_render(row)
    assert rendered["unchanged"]
    assert '<img ' not in rendered["html"]
    assert 'href="' + ARTIFACT + '"' in rendered["html"]
    assert 'href="/ui/backtesting.html?job=awnt_123"' in rendered["html"]
    assert "Открыть исходный отчёт" in rendered["html"]


@pytest.mark.parametrize("change", [
    {"synthetic": True}, {"synthetic": "false"}, {"verification": {"passed": False}},
    {"verification": {"passed": "true"}}, {"status": "queued"}, {"source_kind": "desktop_chart"},
    {"report_url": "https://example.invalid/report"}, {"report_url": "/ui/backtesting.html?job=other"},
    {"source_job_id": "awnt_123\n"}, {"source_job_id": "../private"},
])
def test_chat_report_navigation_requires_exact_completed_verified_provenance(change):
    row = report_message()
    row["actions"][0].update(change)
    rendered = chat_render(row)
    assert rendered["url"] == "" and "Открыть исходный отчёт" not in rendered["html"]
    assert rendered["unchanged"]


@pytest.mark.parametrize("change", [{"source": "ordinary_chat"}, {"role": "user"}])
def test_non_agent_rows_cannot_claim_original_report_navigation(change):
    row = report_message()
    row.update(change)
    assert not chat_render(row)["url"]


def test_actual_desktop_png_and_human_chat_rendering_are_preserved():
    row = report_message()
    row["actions"][0].update(source_kind="desktop_chart", source_job_id=None, report_url=None)
    rendered = chat_render(row)
    assert '<img loading="lazy" src="' + ARTIFACT + '"' in rendered["html"]
    assert rendered["unchanged"] and not rendered["url"]
    row = {"sender_type": "human", "sender_profile_id": "human-1", "sender": {"display_name": "Friend"},
           "content": "Hello", "attachments": [{"url": "/api/sf-chat/files/image.png", "name": "Photo"}]}
    rendered = chat_render(row)
    assert 'class="orch-msg human assistant"' in rendered["html"]
    assert '<img loading="lazy" src="/api/sf-chat/files/image.png"' in rendered["html"]
    assert rendered["unchanged"]


@pytest.mark.parametrize("url", [ARTIFACT + "\n", ARTIFACT + "?download=1", "https://example.invalid/file", "/api/private/file"])
def test_new_artifact_links_only_use_the_opaque_scoped_route(url):
    row = report_message()
    row["attachments"] = [{"type": "artifact", "url": url, "caption": "Unsafe file"}]
    assert "Unsafe file" not in chat_render(row)["html"]


def test_artifact_caption_is_escaped():
    row = report_message()
    row["attachments"][0].update(type="artifact", caption='<img src=x onerror="evil()">')
    rendered = chat_render(row)
    assert '<img ' not in rendered["html"] and "&lt;img" in rendered["html"]


def application_task():
    return {"source_kind": "real_model_response", "status": "succeeded", "synthetic": False,
            "application_result": {"source_kind": "ninjatrader_report", "source_id": "awnt_123", "verified": True}}


def test_verified_application_source_is_projected_without_changing_model_authority():
    value = application_task()
    original = copy.deepcopy(value)
    result = evaluate(f"ui.sourceMeta({json.dumps(value)})")
    assert result == {"kind": "ninjatrader_report", "label": "NinjaTrader · исходный отчёт",
                      "reportUrl": "/ui/backtesting.html?job=awnt_123"}
    assert value == original and value["source_kind"] == "real_model_response"
    value["application_result"]["source_kind"] = "desktop_chart"
    result = evaluate(f"ui.sourceMeta({json.dumps(value)})")
    assert result["kind"] == "desktop_chart" and not result["reportUrl"]


@pytest.mark.parametrize("change", [
    {"status": "waiting"}, {"synthetic": True},
    {"application_result": {"source_kind": "ninjatrader_report", "source_id": "awnt_123", "verified": False}},
    {"application_result": {"source_kind": "ninjatrader_report", "source_id": "awnt_123", "verified": "true"}},
    {"application_result": {"source_kind": "ninjatrader_report", "source_id": "../secret", "verified": True}},
])
def test_plan_or_unverified_result_cannot_link_to_an_application_report(change):
    value = application_task()
    value.update(change)
    assert not evaluate(f"ui.sourceMeta({json.dumps(value)}).reportUrl")


def test_inspector_controls_use_verified_report_link_not_raw_url():
    source = SCRIPT.read_text(encoding="utf-8").split("function drawTask()", 1)[1].split("async function openTask(", 1)[0]
    assert 'href="${esc(source.reportUrl)}"' in source
    assert "Открыть исходный отчёт" in source
    assert "detailRows(rows(detail.outcomes)" in source
    assert "href=\"${esc(task.report_url)}\"" not in source
