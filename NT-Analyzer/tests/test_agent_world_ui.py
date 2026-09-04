"""Executable presentation contracts for the additive Agent World UI.

No running application, external provider or browser profile is used here.
Owner browser acceptance belongs to the integrated implementation checkpoint.
"""
from __future__ import annotations

import json
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
AURORA = ROOT / "app" / "static" / "aurora"
PAGE = AURORA / "ai-command-center.html"
SCRIPT = AURORA / "assets" / "pages" / "ai-command-center.js"
CSS = AURORA / "assets" / "pages" / "ai-command-center.css"
ARTIFACT = "/api/ai-control-center/artifacts/12345678-1234-1234-1234-123456789abc"


def evaluate(expression: str):
    script = (
        "const assert = require('node:assert/strict');\n"
        f"const ui = require({json.dumps(str(SCRIPT))});\n"
        "(async () => { const result = await ("
        + expression
        + "); process.stdout.write(JSON.stringify(result)); })()"
        ".catch(error => { process.stderr.write(String(error.stack)); process.exitCode = 1; });"
    )
    process = subprocess.run(
        ["node", "-e", script], cwd=ROOT, check=True, capture_output=True,
        text=True, encoding="utf-8", timeout=20,
    )
    return json.loads(process.stdout)


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_page_keeps_existing_aurora_shell_and_scoped_assets():
    parser = Tags()
    parser.feed(PAGE.read_text(encoding="utf-8"))
    body = next(attrs for tag, attrs in parser.tags if tag == "body")
    assert body["data-page"] == "ai"
    assert body["data-title"] == "AI Центр"
    assets = [attrs.get("src", "") for tag, attrs in parser.tags if tag == "script"]
    assert assets[-1].startswith("assets/pages/ai-command-center.js")
    assert any(asset.startswith("assets/api.js") for asset in assets)
    assert any(asset.startswith("assets/ui.js") for asset in assets)
    for asset in assets:
        assert not asset.startswith(("http:", "https:", "//"))
        assert (AURORA / asset.split("?")[0]).is_file()
    for tag, attrs in parser.tags:
        if tag == "link" and attrs.get("rel") == "stylesheet":
            assert (AURORA / attrs["href"].split("?")[0]).is_file()
    csp = next(attrs["content"] for tag, attrs in parser.tags if attrs.get("http-equiv") == "Content-Security-Policy")
    assert "script-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'none'" in csp


def test_all_eight_tabs_are_keyboard_addressable_and_admin_tabs_start_hidden():
    parser = Tags()
    parser.feed(PAGE.read_text(encoding="utf-8"))
    tabs = [attrs for tag, attrs in parser.tags if tag == "button" and attrs.get("role") == "tab"]
    assert [tab["data-aw-tab"] for tab in tabs] == [
        "overview", "work", "agents", "decisions", "memory", "experiments", "models", "system",
    ]
    assert all(tab["aria-controls"] == "aw-content" for tab in tabs)
    assert [tab["tabindex"] for tab in tabs] == ["0"] + ["-1"] * 7
    assert all("hidden" in tab for tab in tabs[-2:])
    script = SCRIPT.read_text(encoding="utf-8")
    assert "['ArrowLeft', 'ArrowRight', 'Home', 'End']" in script
    assert "event.key === 'Tab'" in script
    assert "event.key === 'Escape'" in script
    assert "aria-modal" in script


def test_page_uses_existing_transport_and_does_not_create_auth_or_chat_store():
    script = SCRIPT.read_text(encoding="utf-8")
    for name in ["Overview", "Tasks", "Task", "Section", "DemoRun", "TaskChat"]:
        assert f"API.aiControlCenter{name}(" in script
    assert "API = root.API.http" in script
    assert "fetch(" not in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "document.cookie" not in script
    assert "UI.openSFChat({ conversationId: result.conversation_id, conversationType: 'ai' })" in script
    assert "idempotency_key: demoKey" in script


def test_advanced_sections_are_lazy_and_capability_gated():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "qs('#aw-tab-models').hidden = !capability('can_view_models')" in script
    assert "qs('#aw-tab-system').hidden = !capability('can_view_system')" in script
    assert "sections.has(section)" in script
    assert "API.aiControlCenterSection(section, { limit: 50 }, { signal })" in script
    assert "if (request !== generation || disposed) return;\n          sections.set(section, sectionData)" in script
    assert "request !== overviewGeneration" in script
    assert "IN DEVELOPMENT" in script
    assert "href=\"ai-lab.html\"" in script
    assert "href=\"ai-agents.html\"" in script


@pytest.mark.parametrize("payload", [
    None, {}, {"enabled": True}, {"capabilities": {"can_run_demo": True}},
    {"enabled": True, "capabilities": {"can_run_demo": "true"}},
    {"enabled": "true", "capabilities": {"can_run_demo": True}},
    {"enabled": False, "capabilities": {"can_run_demo": True}},
])
def test_demo_action_fail_closed_without_explicit_server_capability(payload):
    assert evaluate(f"ui.canRunDemo({json.dumps(payload)})") is False


def test_demo_action_enabled_only_when_facade_grants_it():
    assert evaluate("ui.canRunDemo({enabled:true, capabilities:{can_run_demo:true}})") is True


@pytest.mark.parametrize("value", ["<img src=x onerror=alert(1)>", '" onclick="evil()', "</script><script>run()</script>", "'&<>\""])
def test_untrusted_labels_are_html_escaped(value):
    rendered = evaluate(f"ui.esc({json.dumps(value)})")
    assert all(char not in rendered for char in '<>"\'')
    assert "&lt;" in rendered or "&quot;" in rendered


@pytest.mark.parametrize("url", [
    "https://example.com/chart.svg", "//example.com/chart.svg", "javascript:alert(1)",
    "data:image/svg+xml,<svg/>", "/api/ai-control-center/artifacts/../../secrets", ARTIFACT + "?url=https://example.com",
    ARTIFACT + "#fragment", ARTIFACT + "/../other", ARTIFACT + "\n", ARTIFACT.replace("/api/", "\\api\\"),
    "/api/ai-control-center/artifacts/not-a-uuid", "/api/ai-lab/private-owner-artifact",
])
def test_artifacts_reject_external_urls_traversal_queries_and_other_namespaces(url):
    assert evaluate(f"ui.safeArtifactUrl({json.dumps(url)})") == ""


def test_only_opaque_scoped_facade_artifact_url_is_accepted():
    assert evaluate(f"ui.safeArtifactUrl({json.dumps(ARTIFACT)})") == ARTIFACT


@pytest.mark.parametrize("sample,score,confidence", [(0, 100, "high"), (1, 100, "low"), (2, 100, "low"), (3, None, "low"), (20, 95, "insufficient")])
def test_insufficient_samples_are_new_never_zero_quality(sample, score, confidence):
    result = evaluate(f"ui.evaluationMeta({json.dumps({'evaluation': {'sample_size': sample, 'score_pct': score, 'confidence': confidence}})})")
    assert result["insufficient"] is True
    assert result["label"] == "NEW"
    assert result["score"] is None
    assert result["sample"] == sample


def test_observed_score_kept_separate_from_stable_rating():
    result = evaluate("ui.evaluationMeta({evaluation:{sample_size:1,score_pct:null,observed_score_pct:100,confidence:'low'}})")
    assert result["label"] == "NEW"
    assert result["observed"] == 100
    result = evaluate("ui.evaluationMeta({evaluation:{sample_size:3,score_pct:100,confidence:'low'}})")
    assert result["label"] == "100%"
    assert result["confidence"] == "низкая"


@pytest.mark.parametrize("value,expected", [(None, "—"), (0, "0%"), (-10, "0%"), (130, "100%"), ("invalid", "—")])
def test_numeric_presentation_does_not_invent_missing_observations(value, expected):
    assert evaluate(f"ui.pct({json.dumps(value)})") == expected


def test_shared_status_vocabulary_rejects_injected_css_or_labels():
    result = evaluate("[ui.statusMeta('running'),ui.statusMeta('failed'),ui.statusMeta('court'),ui.badge('<img onerror=1>')]")
    assert result[:3] == [["В работе", "good"], ["Ошибка", "error"], ["Разбор Court", "review"]]
    assert "<img" not in result[3]
    assert "Статус не указан" in result[3]


def test_task_filters_preserve_status_and_search_semantics():
    result = evaluate("""(() => {
      const task = {title:'Проверка графика', status:'succeeded', lead:{display_name:'Иван'}, task_class:'chart'};
      return [ui.taskMatches(task,'completed','ИВАН'),ui.taskMatches(task,'active',''),ui.taskMatches(task,'all','unknown'),ui.taskMatches({status:'blocked'},'review','')];
    })()""")
    assert result == [True, False, False, True]


def test_flag_display_uses_strict_booleans():
    assert evaluate("ui.flagRows({A:true,B:'true',C:false,D:{enabled:true},E:{enabled:'true'}})") == [
        {"name": "A", "enabled": True}, {"name": "B", "enabled": False},
        {"name": "C", "enabled": False}, {"name": "D", "enabled": True}, {"name": "E", "enabled": False},
    ]


def test_chart_snapshot_is_actual_browser_png_rasterization_with_bounded_dimensions():
    result = evaluate("""(async () => {
      const seen = {}, canvas = {getContext: () => ({drawImage: (_img,x,y,w,h) => {seen.draw=[x,y,w,h];}}),toDataURL: media => {seen.media=media;return 'data:image/png;base64,AAAA';}};
      class Picture {constructor(){this.naturalWidth=2400;this.naturalHeight=1000;} set src(value){seen.url=value;queueMicrotask(() => this.onload());}}
      const env={Image:Picture,setTimeout,clearTimeout,document:{createElement:tag=>{seen.tag=tag;return canvas;}}};
      const result=await ui.captureChart({url:'/api/ai-control-center/artifacts/12345678-1234-1234-1234-123456789abc',media_type:'image/svg+xml'},env);
      return {seen,result,width:canvas.width,height:canvas.height};
    })()""")
    assert result["seen"]["tag"] == "canvas"
    assert result["seen"]["media"] == "image/png"
    assert result["seen"]["draw"] == [0, 0, 1200, 500]
    assert result["seen"]["url"] == ARTIFACT
    assert result["width"] == 1200
    assert result["height"] == 500


def test_chart_snapshot_cannot_load_external_or_non_svg_image():
    result = evaluate("""(async () => {
      let created=0; const env={Image:class {constructor(){created++;}}};
      const errors=[];
      for(const value of [{url:'https://example.com/chart.svg',media_type:'image/svg+xml'},{url:'/api/ai-control-center/artifacts/12345678-1234-1234-1234-123456789abc',media_type:'image/png'}]){
        try{await ui.captureChart(value,env);}catch(error){errors.push(error.message);}
      }
      return {created,errors:errors.length};
    })()""")
    assert result == {"created": 0, "errors": 2}


def test_styles_do_not_redefine_global_shell_or_chart_engine():
    css = CSS.read_text(encoding="utf-8")
    assert ":root" not in css
    assert re.search(r"(?:^|[\n}])\s*body\s*\{", css) is None
    assert ".rail" not in css
    assert "#price-chart" not in css
    assert "@media (max-width: 720px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert ".aw-table-wrap" in css and "overflow-x: auto" in css


def test_source_does_not_invent_quality_ranks_or_execute_risky_actions():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "Критерии конкретного класса задач" in script
    assert "не доказывает качество LLM" in script
    assert "shadow" not in script.lower() or "SHADOW" in script
    assert "court/approve" not in script
    assert "trade/execute" not in script
    assert "localStorage" not in script
    assert "Math.random" not in script
    assert "исход" in script.lower() or "Исходные данные тестовые" in script
