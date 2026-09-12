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
DESKTOP_ARTIFACT = "/api/ops/runtime/snapshots/cs_" + "a" * 32 + ".jpg"


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


def test_exactly_three_main_views_keep_inspectors_on_the_same_page():
    parser = Tags()
    parser.feed(PAGE.read_text(encoding="utf-8"))
    tabs = [attrs for tag, attrs in parser.tags if tag == "button" and attrs.get("role") == "tab"]
    assert [tab["data-aw-tab"] for tab in tabs] == [
        "overview", "work", "agents",
    ]
    assert all(tab["aria-controls"] == "aw-content" for tab in tabs)
    assert [tab["tabindex"] for tab in tabs] == ["0", "-1", "-1"]
    assert all("hidden" not in tab for tab in tabs)
    script = SCRIPT.read_text(encoding="utf-8")
    assert "['ArrowLeft', 'ArrowRight', 'Home', 'End']" in script
    assert "event.key === 'Tab'" in script
    assert "event.key === 'Escape'" in script
    assert "aria-modal" in script
    assert "const TABS = ['overview', 'work', 'agents']" in script
    assert "currentDrawer = UI.drawer(" in script
    assert "root.location.href" not in script


def test_page_uses_existing_transport_and_does_not_create_auth_or_chat_store():
    script = SCRIPT.read_text(encoding="utf-8")
    for name in ["Overview", "Tasks", "Task", "DemoRun", "TaskChat"]:
        assert f"API.aiControlCenter{name}(" in script
    assert "API = root.API.http" in script
    assert "fetch(" not in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "document.cookie" not in script
    assert "UI.openSFChat({ conversationId: result.conversation_id, conversationType: 'ai' })" in script
    assert "idempotency_key: demoKey" in script


def test_domain_tools_remain_accessible_on_one_page_and_load_only_on_request():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "function foundationCard()" in script
    parser = Tags()
    parser.feed(PAGE.read_text(encoding="utf-8"))
    launcher = [attrs["data-aw-domain"] for tag, attrs in parser.tags if "data-aw-domain" in attrs]
    assert launcher == ["decisions", "memory", "experiments", "models", "projects", "routines", "calendar", "publications", "system"]
    assert "capability('can_view_system') ? flagRows(overview.flags) : []" in script
    assert "API.aiControlCenterSection(" not in script
    for method in ["Domain", "DomainItem", "DomainAction"]:
        assert f"API.aiControlCenter{method}(" in script
    assert "request !== overviewGeneration" in script
    assert "IN DEVELOPMENT" in script
    card = script.split("function foundationCard()", 1)[1].split("function realWorkHint", 1)[0]
    assert "href=" not in card
    assert "data-aw-domain=\"personas\"" in card


def test_overview_places_work_results_team_and_rating_together_without_sample_values():
    script = SCRIPT.read_text(encoding="utf-8")
    overview = script.split("function renderOverview()", 1)[1].split("function taskTable", 1)[0]
    assert 'aw-column-work' in overview
    assert 'aw-column-results' in overview
    assert 'aw-column-team' in overview
    assert 'Команда и рейтинг' in overview
    assert 'Результаты и исходные данные' in overview
    assert 'overviewOutcomes(overview)' in overview
    assert 'stats.active_tasks' in overview
    assert 'stats.completed_tasks' in overview
    assert 'attentionKnown && number(stats.attention) === 0' in overview
    assert 'Отсутствие данных не означает' in overview
    assert 'n = ${count(evaluation.sample)}' in script


@pytest.mark.parametrize("value", [
    {}, {"synthetic": False}, {"source_kind": "ninjatrader_report", "source_job_id": "job-123"},
    {"synthetic": "false", "source_kind": "desktop_chart"},
    {"synthetic": False, "source_kind": "unverified_external_source"},
    {"synthetic": False, "source_kind": "__proto__"},
    {"synthetic": False, "source_kind": "constructor"},
])
def test_real_source_labels_require_explicit_supported_server_provenance(value):
    source = evaluate(f"ui.sourceMeta({json.dumps(value)})")
    assert source == {"label": "Источник не подтверждён", "kind": "unknown", "reportUrl": ""}


@pytest.mark.parametrize("job", ["../secret", "//example.com", "<img>", "x?admin=1", "job/another", "job%2Fprivate", "job\n", "x" * 161])
def test_existing_report_link_rejects_paths_queries_and_markup(job):
    value = {"synthetic": False, "source_kind": "ninjatrader_report", "source_job_id": job}
    assert evaluate(f"ui.sourceMeta({json.dumps(value)}).reportUrl") == ""


def test_real_report_uses_existing_backtesting_route_and_synthetic_cannot_claim_it():
    source = {"synthetic": False, "source_kind": "ninjatrader_report", "source_job_id": "nt:job_123.v1"}
    result = evaluate(f"ui.sourceMeta({json.dumps(source)})")
    assert result["reportUrl"] == "/ui/backtesting.html?job=nt%3Ajob_123.v1"
    assert result["label"] == "NinjaTrader · исходный отчёт"
    source["synthetic"] = True
    result = evaluate(f"ui.sourceMeta({json.dumps(source)})")
    assert result["kind"] == "synthetic"
    assert result["reportUrl"] == ""


def test_overview_outcomes_keep_explicit_empty_and_source_classification():
    assert evaluate("ui.overviewOutcomes({outcomes:[],tasks:[{id:'one',status:'completed',summary:'stored'}]})") == []
    assert evaluate("ui.overviewOutcomes({tasks:[{id:'one',status:'running'}]})") == []
    result = evaluate("ui.overviewOutcomes({tasks:[{id:'one',status:'completed',summary:'Stored result',synthetic:true},{id:'two',status:'completed',synthetic:false,source_kind:'ninjatrader_report',source_job_id:'nt-job'}]})")
    assert result[0]["summary"] == "Stored result"
    assert result[0]["synthetic"] is True
    assert "artifact" not in result[0]
    assert result[1]["synthetic"] is False
    assert result[1]["source_job_id"] == "nt-job"


@pytest.mark.parametrize("data", [None, {}, {"enabled": True}, {"enabled": True, "scope": {"synthetic": True}}, {"enabled": True, "scope": {"synthetic": "false"}}, {"enabled": False, "scope": {"synthetic": False}}])
def test_real_chat_hints_require_explicit_non_synthetic_workspace(data):
    assert evaluate(f"ui.realChatCommands({json.dumps(data)})") == []


def test_real_chat_hints_reuse_existing_chat_not_a_backtest_composer():
    commands = evaluate("ui.realChatCommands({enabled:true,scope:{synthetic:false}})")
    assert len(commands) == 2
    assert commands[0]["text"] == "Толик, запусти бэктест SampleMACrossOver на MNQ 09-26, 5m, с 2026-08-24 по 2026-08-29, Fast=10, Slow=25"
    assert commands[1]["text"] == "Иван, сделай снимок рабочего стола MNQ 09-26, 5m"
    source = SCRIPT.read_text(encoding="utf-8")
    assert "target.hasAttribute('data-aw-real-chat')) UI.openSFChat({ conversationType: 'ai' })" in source
    assert "Даты бэктеста — UTC; конечная дата не включается" in source
    assert "API.submit" not in source
    assert "API.backtest" not in source


def test_canonical_ready_tasks_remain_visible_as_queued_in_active_and_waiting_views():
    result = evaluate("({label:ui.statusMeta('ready'),active:ui.taskMatches({status:'ready'},'active',''),waiting:ui.taskMatches({status:'ready'},'waiting',''),completed:ui.taskMatches({status:'ready'},'completed','')})")
    # Integration narrowed the waiting filter: a queued task is execution, and
    # "Ожидают" now means waiting for a result rather than waiting to start.
    assert result == {"label": ["В очереди", "neutral"], "active": True, "waiting": False, "completed": False}
    assert evaluate("ui.taskMatches({display_status:'waiting_result'},'waiting','')") is True
    # A queued task belongs to execution. The overview panel used to widen this
    # set with review/blocked/planned, which is why its heading contradicted the
    # "В работе" metric; the phase split replaced that union.
    # phaseOf now groups the single projection's display states, not raw ledger
    # statuses: one computation on the server, one view of it on the page.
    phases = evaluate("({queued:ui.phaseOf({display_status:'queued'}),running:ui.phaseOf({display_status:'running'}),"
                      "waiting:ui.phaseOf({display_status:'waiting_result'}),"
                      "review:ui.phaseOf({display_status:'awaiting_review'}),"
                      "blocked:ui.phaseOf({display_status:'blocked'}),"
                      "unconfirmed:ui.phaseOf({display_status:'result_received'}),"
                      "auto:ui.phaseOf({display_status:'verified_automatically'}),"
                      "done:ui.phaseOf({display_status:'completed'})})")
    assert phases == {"queued": "executing", "running": "executing", "waiting": "executing",
                      "review": "awaiting_review", "blocked": "awaiting_decision",
                      "unconfirmed": "result_unconfirmed", "auto": "done", "done": "done"}


def test_working_runtime_agent_alias_has_running_style_and_active_filter():
    result = evaluate("({alias:ui.statusMeta('working'),running:ui.statusMeta('running'),active:ui.taskMatches({status:'working'},'active',''),waiting:ui.taskMatches({status:'working'},'waiting','')})")
    assert result["alias"] == result["running"] == ["В работе", "good"]
    assert result["active"] is True and result["waiting"] is False


def test_compact_overview_boots_without_hidden_tab_nodes_or_extra_api_requests():
    result = evaluate("""(async () => {
      const fs = require('node:fs'), vm = require('node:vm');
      let started, requests = 0;
      const nodes = new Map();
      const tabs = ['overview','work','agents'].map(key => ({dataset:{awTab:key},setAttribute(){}}));
      const node = key => {
        if (!nodes.has(key)) nodes.set(key,{innerHTML:'',textContent:'',hidden:false,
          setAttribute(){},addEventListener(){},classList:{toggle(){}},contains(){return false;},
          querySelectorAll(selector){return selector.includes('[data-aw-tab]')?tabs:[];}});
        return nodes.get(key);
      };
      const document = {querySelector:node,addEventListener(){},removeEventListener(){}};
      const data = {enabled:true,scope:{synthetic:false},capabilities:{can_run_demo:false},
        stats:{active_tasks:0,completed_tasks:1,agents:1,attention:0},attention:[],
        agents:[{id:'persona-1',display_name:'<Agent>',status:'idle',evaluation:{sample_size:1,score_pct:100}}],
        tasks:[{id:'task-1',title:'Stored task',status:'completed',synthetic:true}],
        outcomes:[{title:'<script>unsafe()</script>',summary:'Recorded NT result',task_id:'task-2',synthetic:false,source_kind:'ninjatrader_report',source_job_id:'nt-2',status:'verified'},
          {title:'Actual Desktop capture',task_id:'task-3',synthetic:false,source_kind:'desktop_chart',artifact:{url:'/api/ops/runtime/snapshots/cs_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg',title:'Recorded image',media_type:'image/jpeg'}}]};
      const window = {UI:{ready(fn){started=fn();},signal(){},onLeave(){},wireAgentFaces(){}},
        API:{http:{async aiControlCenterOverview(){requests++;return data;}}},
        location:{hash:'',search:''}};
      const source = fs.readFileSync(require.resolve(PATH_TO_SCRIPT),'utf8');
      vm.runInNewContext(source,{window,document,URLSearchParams,Date});
      await started;
      return {requests,html:node('#aw-content').innerHTML,pulse:node('#aw-pulse').innerHTML};
    })()""".replace("PATH_TO_SCRIPT", json.dumps(str(SCRIPT))))
    assert result["requests"] == 1
    assert all(name in result["html"] for name in [
        "aw-column-work", "aw-column-results", "aw-column-team",
    ]), result["html"]
    assert "NEW" in result["html"]
    # The mini card leads with the observation count rather than "n = N";
    # the claim it must keep making is that the sample size is visible.
    assert "1 наблюдений" in result["html"]
    assert "<script>unsafe()" not in result["html"]
    assert "&lt;script&gt;unsafe()&lt;/script&gt;" in result["html"]
    assert "/ui/backtesting.html?job=nt-2" in result["html"]
    assert "Recorded NT result" in result["html"]
    assert "IN DEVELOPMENT" in result["html"]
    assert '<img src="' + DESKTOP_ARTIFACT + '"' in result["html"]


@pytest.mark.parametrize("suffix", ["jpg", "png", "webp"])
def test_confirmed_desktop_artifact_uses_existing_authenticated_snapshot_route(suffix):
    path = DESKTOP_ARTIFACT.rsplit(".", 1)[0] + "." + suffix
    assert evaluate(f"ui.safeArtifactUrl({json.dumps(path)}, 'desktop_chart')") == path
    assert evaluate(f"ui.safeArtifactUrl({json.dumps(path)})") == ""


@pytest.mark.parametrize("source", [
    {}, {"synthetic": True, "source_kind": "desktop_chart"},
    {"synthetic": False, "source_kind": "ninjatrader_report"},
    {"source_kind": "desktop_chart"},
])
def test_unconfirmed_and_synthetic_data_cannot_embed_legacy_desktop_snapshot(source):
    assert evaluate(f"ui.safeArtifactUrl({json.dumps(DESKTOP_ARTIFACT)}, ui.sourceMeta({json.dumps(source)}).kind)") == ""


@pytest.mark.parametrize("path", [
    DESKTOP_ARTIFACT + "?download=1", DESKTOP_ARTIFACT + "#image", DESKTOP_ARTIFACT + "/../private",
    "https://example.com" + DESKTOP_ARTIFACT, "/api/ops/runtime/snapshots/../private.jpg",
    "/api/ops/runtime/snapshots/cs_invalid.jpg", DESKTOP_ARTIFACT.replace(".jpg", ".svg"),
    DESKTOP_ARTIFACT.replace(".jpg", ".jpg.html"), DESKTOP_ARTIFACT.replace("cs_", "CS_"),
])
def test_desktop_snapshot_urls_reject_unapproved_paths_queries_and_formats(path):
    assert evaluate(f"ui.safeArtifactUrl({json.dumps(path)}, 'desktop_chart')") == ""


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
    # The claim, not one phrasing of it: a passed check must never read as a
    # judgement of the model in general. Integration reworded the sentences, so
    # both surviving statements are pinned instead of the old exact string.
    assert "общая оценка модели" in script
    assert "не оценивает качество LLM" in script
    assert "shadow" not in script.lower() or "SHADOW" in script
    assert "court/approve" not in script
    assert "trade/execute" not in script
    assert "localStorage" not in script
    assert "Math.random" not in script
    assert "исход" in script.lower() or "Исходные данные тестовые" in script


@pytest.mark.parametrize("domain", ["personas", "decisions", "memory", "projects", "routines", "calendar", "models", "model_tasks", "experiments", "system", "publications"])
def test_all_requested_domains_have_known_same_page_routes(domain):
    assert evaluate(f"ui.knownDomain({json.dumps(domain)})") is True


@pytest.mark.parametrize("domain", [None, "__proto__", "constructor", "../../secrets", "community", "trade", "production"])
def test_generic_domain_ui_does_not_accept_arbitrary_routes(domain):
    assert evaluate(f"ui.knownDomain({json.dumps(domain)})") is False


def test_domain_actions_require_enabled_server_projection_and_explicit_allowlist():
    result = evaluate("[ui.allowedDomainActions({enabled:true,actions:['create','execute','__proto__']}),ui.allowedDomainActions({enabled:false,actions:['create']}),ui.allowedDomainActions({enabled:'true',actions:['create']}),ui.allowedDomainActions({enabled:true,actions:['create']},{actions:['update','archive','delete_everything']}),ui.allowedDomainActions({enabled:true,capabilities:{can_create:true}})]")
    assert result == [["create"], [], [], ["update", "archive"], []]


def test_persona_payload_is_distinct_from_model_credentials_scope_and_role_authority():
    payload = {"name": "Research helper", "description": "Local comparison", "style": "Concise", "avatar_key": "tolik", "workspace_id": "foreign", "api_key": "secret", "permissions": ["admin"], "model": "injected", "role": "owner"}
    result = evaluate(f"ui.domainPayload('personas','create',{json.dumps(payload)})")
    # A face is part of the Persona; credentials, scope, model and authority are not.
    assert result == {"name": "Research helper", "description": "Local comparison",
                      "style": "Concise", "avatar_key": "tolik", "application_role": ""}
    assert not {"workspace_id", "api_key", "permissions", "model", "role"} & set(result)


def test_persona_face_must_be_one_of_the_shipped_agent_assets():
    """A free-text name must never let a Persona borrow another agent's face."""
    from app.ai_control_center.presentation import avatar_key, AVATAR_KEYS
    assert avatar_key("tolik") == "tolik" and avatar_key("TOLIK") == "tolik"
    for value in ["", "../vitek", "unknown", "Толик", None, 7]:
        assert avatar_key(value) == ""
    assert set(evaluate("ui.AVATAR_KEYS")) == set(AVATAR_KEYS)


@pytest.mark.parametrize("domain,action,values,expected", [
    ("memory", "create", {"title": "Note", "content": "Measured output", "purpose": "Review", "retention_days": "14"}, {"title": "Note", "content": "Measured output", "purpose": "Review", "retention_days": 14, "source_ids": []}),
    ("projects", "create", {"title": "Strategy", "strategy_key": "SampleMACrossOver"}, {"title": "Strategy", "description": "", "strategy_key": "SampleMACrossOver"}),
    ("routines", "create", {"title": "Weekly review", "interval_minutes": "10080"}, {"title": "Weekly review", "description": "", "interval_minutes": 10080, "source_ids": []}),
    ("projects", "version", {"notes": "Change Fast", "parameters": '{"Fast": 10, "Slow": 25}'}, {"notes": "Change Fast", "parameters": {"Fast": 10, "Slow": 25}}),
    ("memory", "revoke", {"reason": "No longer current", "content": "must not rewrite"}, {"reason": "No longer current"}),
    ("models", "test", {"rubric_key": "extract_facts", "input_text": "must not send"}, {}),
    ("models", "disconnect", {"api_key": "must not send", "scope": "foreign"}, {}),
    ("tasks", "cancel", {"reason": "Owner cancelled", "job_id": "foreign"}, {"reason": "Owner cancelled"}),
])
def test_domain_form_payloads_match_actual_service_fields(domain, action, values, expected):
    assert evaluate(f"ui.domainPayload({json.dumps(domain)},{json.dumps(action)},{json.dumps(values)})") == expected


@pytest.mark.parametrize("domain,action,values", [
    ("memory", "create", {"title": "Note", "content": "x", "purpose": "Review", "retention_days": "0"}),
    ("memory", "create", {"title": "Note", "content": "x", "purpose": "Review", "retention_days": "366"}),
    ("routines", "create", {"title": "Too frequent", "interval_minutes": "4"}),
    ("routines", "create", {"title": "Invalid", "interval_minutes": "5.5"}),
    ("projects", "version", {"notes": "Invalid", "parameters": "[]"}),
    ("projects", "version", {"notes": "Invalid", "parameters": '{"__proto__": {"admin": true}}'}),
    ("projects", "version", {"notes": "Invalid", "parameters": "not JSON"}),
    ("projects", "create", {"title": "Missing strategy key"}),
    ("calendar", "create", {"title": "Backwards", "starts_at": "2026-09-05T00:00:00Z", "ends_at": "2026-09-04T00:00:00Z"}),
    ("calendar", "create", {"title": "Invalid", "starts_at": "not a date", "ends_at": "2026-09-05T00:00:00Z"}),
    ("tasks", "cancel", {"reason": ""}),
])
def test_domain_forms_reject_invalid_values_before_network(domain, action, values):
    assert evaluate(f"(() => {{ try {{ ui.domainPayload({json.dumps(domain)},{json.dumps(action)},{json.dumps(values)}); return false; }} catch (error) {{ return Boolean(error.message); }} }})()") is True


def test_calendar_preserves_explicit_time_and_sends_utc_not_owner_scope():
    result = evaluate("ui.domainPayload('calendar','create',{title:'Research review',starts_at:'2026-09-04T12:30:00-07:00',ends_at:'2026-09-04T13:30:00-07:00',workspace_id:'foreign'})")
    assert result == {"title": "Research review", "description": "", "starts_at": "2026-09-04T19:30:00.000Z", "ends_at": "2026-09-04T20:30:00.000Z", "source_ids": []}


def test_court_form_collects_evidence_and_model_ids_never_votes_or_execution_permission():
    identity = "12345678-1234-1234-1234-123456789abc"
    decision = {"title": "Review", "proposal": "Test strategy", "evidence_ids": [identity], "risk": "moderate", "trigger": "requested_review", "verdict": "approved", "votes": ["yes"], "execution_allowed": True}
    result = evaluate(f"ui.domainPayload('decisions','create',{json.dumps(decision)})")
    assert set(result) == {"title", "proposal", "evidence_ids", "risk", "trigger"}
    ids = [identity, identity[:-1] + "d", identity[:-1] + "e"]
    result = evaluate(f"ui.domainPayload('decisions','review',{json.dumps({'model_ids': ids, 'votes': ['approved']})})")
    assert result == {"model_ids": ids}
    invalid = {"model_ids": [identity, identity, identity]}
    assert evaluate(f"(() => {{try {{ui.domainPayload('decisions','review',{json.dumps(invalid)});return false;}}catch (_){{return true;}}}})()") is True


def test_model_connect_form_uses_server_providers_and_never_returns_the_stored_secret():
    fields = evaluate("ui.domainFormFields('models','connect')")
    provider = next(field for field in fields if field["key"] == "provider")
    secret = next(field for field in fields if field["key"] == "api_key")
    assert provider["type"] == "provider" and "options" not in provider
    assert secret["type"] == "password"
    source = SCRIPT.read_text(encoding="utf-8")
    assert "dependencies.models?.providers" in source
    assert "spec.type === 'password' ? ''" in source
    assert 'autocomplete="new-password"' in source
    assert "keyInput.value = ''" in source
    assert "person.status === 'active'" in source


def test_model_response_evidence_uses_actual_checks_and_scope_not_a_fake_llm_rating():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "value.rubric || value.checks" in source
    assert "value.verifier || value.evaluator" in source
    assert "value.score_pct ?? value.observed_score_pct" in source
    assert "value.response_sha256" in source
    assert "value.input_sha256" in source
    assert "item.court_cases" in source
    assert "vote.model_key" in source and "vote.session_id" in source
    result = evaluate("ui.sourceMeta({synthetic:false,source_kind:'real_model_response'})")
    assert result == {"kind": "real_model_response", "label": "Модель · фактический ответ", "reportUrl": ""}


def test_server_errors_and_structured_preview_cannot_echo_provider_secrets():
    result = evaluate("({message:ui.domainError({status:500,message:'api_key=private-secret',code:'private-secret'}),json:ui.publicJSON({safe:'Keep',nested:{api_key:'secret',password:'secret',authorization:'secret'},metrics:{score:99}})})")
    assert "private-secret" not in result["message"]
    assert "secret" not in result["json"]
    assert "Keep" in result["json"] and '"score": 99' in result["json"]


def test_mutation_envelope_revision_idempotency_and_manual_external_consent_are_explicit():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "{ payload, idempotency_key: state.key }" in source
    assert "body.expected_revision = state.revision" in source
    assert "!form.reportValidity()" in source
    assert 'name="confirmation" required' in source
    assert "name=\"confirmation\" checked" not in source
    assert "task.allowed_actions" in source
    assert "API.aiControlCenterDomainAction(state.domain, state.id, state.action, body)" in source


def run_domain_ui(scenario: str):
    """Run the real event handlers with a minimal DOM, never a browser/account."""
    code = r"""(async () => {
      const fs = require('node:fs'), vm = require('node:vm');
      const calls=[], listeners={}, nodes=new Map(); let started, drawer, seq=0, failPost=false, previewOverrides={};
      const ids={persona:'11111111-1111-1111-1111-111111111111',model:'22222222-2222-2222-2222-222222222222',task:'33333333-3333-3333-3333-333333333333'};
      const task={id:ids.task,title:'Actual task',status:'ready',revision:7,allowed_actions:['cancel'],actions:['cancel'],source_kind:'real_model_response',synthetic:false,lead:{id:ids.persona,display_name:'Owner persona'},model:'requested-model'};
      const response={...task,task,result_text:'ACTUAL_RESPONSE',actual_model:'provider-receipt-model',evaluation:{observed_score_pct:100,evaluator:'independent_local_evidence_verifier',rubric_key:'connection_exact',checks:[{key:'exact_response',passed:true}],response_sha256:'a'.repeat(64)}};
      const domains={
        personas:{enabled:true,actions:['create'],items:[{id:ids.persona,title:'Owner persona',name:'Owner persona',status:'active',revision:7,actions:['update','suspend'],description:'Owned description'}]},
        models:{enabled:true,actions:['connect'],providers:[{id:'deepseek',label:'Server-listed provider'}],items:[{id:ids.model,title:'Own model',label:'Own model',model:'requested-model',provider:'deepseek',connected:true,credentials_configured:true,status:'active',actions:['test','task','disconnect'],api_key:'must-not-render-returned-secret'}]},
        model_tasks:{enabled:true,actions:[],items:[response]},
        experiments:{enabled:true,actions:['create'],items:[]},
        memory:{enabled:true,actions:['create'],items:[]},
        decisions:{enabled:true,actions:['create'],items:[],evidence_candidates:[{id:ids.task,title:'Stored JSON evidence',media_type:'application/json',sha256:'b'.repeat(64)}]},
        projects:{enabled:true,actions:['create'],items:[]},routines:{enabled:true,actions:['create'],items:[]},calendar:{enabled:true,actions:['create'],items:[]},
        publications:{enabled:true,actions:['prepare'],items:[],source_candidates:[{source_kind:'outcome',source_id:ids.task,title:'Verified result for review'}]},
        system:{enabled:true,actions:[],items:[{id:'runtime',title:'Real runtime state',status:'active',summary:'Recorded status',fields:{secret:'must-not-render-system-secret',state:'healthy'}}]},
      };
      const tabs=['overview','work','agents'].map(key=>({dataset:{awTab:key},setAttribute(){}}));
      function node(key){if(!nodes.has(key))nodes.set(key,{innerHTML:'',textContent:'',hidden:false,disabled:false,setAttribute(){},addEventListener(){},focus(){},classList:{toggle(){}},querySelectorAll(){return key==='#aw-center'?tabs:[];},contains(target){return target.area==='shell';}});return nodes.get(key);}
      const document={activeElement:{focus(){}},querySelector:node,addEventListener(type,fn){listeners[type]=fn;},removeEventListener(){}};
      const state={enabled:true,scope:{synthetic:false,workspace_id:'own'},capabilities:{},stats:{active_tasks:1,completed_tasks:0,agents:0,attention:0},tasks:[task],agents:[],attention:[]};
      const http={
        async aiControlCenterOverview(){calls.push({method:'overview'});return state;},
        async aiControlCenterTasks(){return {items:[task]};},
        async aiControlCenterTask(id){calls.push({method:'task',id});return {...response,task};},
        async aiControlCenterDomain(domain,params){calls.push({method:'list',domain,params});if(!domains[domain])throw {status:404};return JSON.parse(JSON.stringify(domains[domain]));},
        async aiControlCenterDomainItem(domain,id){calls.push({method:'detail',domain,id});const item=domains[domain].items.find(item=>item.id===id);if(!item)throw {status:404};return JSON.parse(JSON.stringify(item));},
        async aiControlCenterDomainAction(domain,id,action,body){calls.push({method:'post',domain,id,action,body:JSON.parse(JSON.stringify(body))});if(failPost)throw {status:500,message:'leaked credential must-not-render-error-secret'};
          if(domain==='publications'&&action==='prepare')return {snapshot:{source_id:body.payload.source_id,source_revision:7,title:'Reviewed <script>snapshot</script>',summary:'Only public verified fields',synthetic:false,kind:'Agent World Result',timestamp_utc:'2026-09-05T12:00:00Z',metrics:{Checks:4},evidence_sha256:['a'.repeat(64)],limitations:['Not general model quality'],raw_response:'must-not-render-private-answer',api_key:'must-not-render-published-secret'},snapshot_sha256:'b'.repeat(64),source_revision:7,permanent:true,requires_explicit_confirmation:true,...previewOverrides};
          if(domain==='publications'&&action==='publish')return {ok:true,post:{id:'existing-social-post'},snapshot_sha256:body.payload.approved_snapshot_sha256,permanent:true,published_to:'sf_social'};
          if(domain==='models'&&['test','task'].includes(action))return response;
          if(domain==='tasks'){task.status='cancelled';task.allowed_actions=[];return {task};}
          const old=id==='new'?{}:domains[domain].items.find(item=>item.id===id)||{};
          const item={...old,...body.payload,id:id==='new'?ids.persona:id,title:body.payload.title||body.payload.name||old.title,status:'active',revision:(old.revision||0)+1,actions:['update']};
          const at=domains[domain].items.findIndex(row=>row.id===item.id);if(at<0)domains[domain].items.push(item);else domains[domain].items[at]=item;return {ok:true,item};
        },
      };
      const window={UI:{ready(fn){started=fn();},signal(){},onLeave(){},wireAgentFaces(){},closeDrawer(){if(drawer)drawer.closed=true;},drawer(title,html){
        drawer={title,innerHTML:html,closed:false,classList:{contains(value){return value==='open'&&!drawer.closed;},add(){}},setAttribute(){},focus(){},querySelector(selector){return selector==='.aw-inspector'?{}:null;},querySelectorAll(){return[];},contains(target){return target.area==='drawer';}};return drawer;
      }},API:{http},location:{hash:'',search:''},history:{replaceState(_a,_b,url){window.location.hash=url;}},crypto:{randomUUID(){return '44444444-4444-4444-4444-'+String(++seq).padStart(12,'0');}},clearTimeout(){}};
      vm.runInNewContext(fs.readFileSync(require.resolve(PATH_TO_SCRIPT),'utf8'),{window,document,URLSearchParams,Date}); await started;
      async function settle(){for(let i=0;i<12;i++)await Promise.resolve();await new Promise(resolve=>setImmediate(resolve));}
      async function click(dataset,area='drawer'){
        const target={dataset,area,hasAttribute(name){return name==='data-aw-domain-refresh'&&dataset.refresh===true;},closest(selector){return selector==='button, a'?target:selector==='.aw-inspector'?{}:null;}};
        listeners.click({target});await settle();return drawer?.innerHTML||'';
      }
      function form(values={},confirmation=false){
        const html=drawer.innerHTML, error={textContent:'',hidden:true}, controls={};
        for(const [key,value]of Object.entries(values))controls[key]={value};
        const result={id:'aw-domain-form',area:'drawer',elements:{namedItem(key){return controls[key]||null;}},reportValidity(){return !html.includes('name="confirmation" required')||confirmation;},
          querySelector(selector){return selector==='#aw-form-error'?error:null;},querySelectorAll(selector){if(selector==='button, input, select, textarea')return Object.values(controls);const match=selector.match(/input\[name="([^"]+)"\]:checked/);return match?(Array.isArray(values[match[1]])?values[match[1]].map(value=>({value})):[]):[];},error,controls};return result;
      }
      async function submit(f){await listeners.submit({target:f,preventDefault(){}});await settle();}
      SCENARIO
    })()"""
    return evaluate(code.replace("PATH_TO_SCRIPT", json.dumps(str(SCRIPT))).replace("SCENARIO", scenario))


def test_domain_models_form_uses_real_handlers_and_server_listed_provider_only():
    result = run_domain_ui("""
      const initial=calls.length;
      await click({awDomain:'models'},'shell');
      const list=drawer.innerHTML;
      await click({awDomainAction:'connect',awEntity:'new'});
      return {initial,list,form:drawer.innerHTML,calls};
    """)
    assert result["initial"] == 1
    assert "Own model" in result["list"]
    assert "must-not-render-returned-secret" not in result["list"]
    assert "Server-listed provider" in result["form"]
    assert 'value="deepseek"' in result["form"]
    assert 'type="password" value=""' in result["form"]
    assert [(call["method"], call.get("domain")) for call in result["calls"]] == [("overview", None), ("list", "models"), ("list", "personas")]
    assert not any(call["method"] == "post" for call in result["calls"])


def test_calendar_detail_renders_local_time_and_accepted_label():
    result = run_domain_ui("""
      const starts='2026-09-05T07:00:00.000Z';
      domains.calendar.items=[{id:ids.task,title:'Calendar review',status:'accepted',revision:2,
        description:'Manual only',starts_at:starts,ends_at:'2026-09-05T07:30:00.000Z'}];
      await click({awDomain:'calendar'},'shell');
      await click({awDomainItem:ids.task});
      return {html:drawer.innerHTML,local:new Date(starts).toLocaleString('ru-RU',{dateStyle:'short',timeStyle:'short'})};
    """)
    assert result["local"] in result["html"]
    assert '2026-09-05T07:00:00.000Z' not in result["html"]
    assert 'Принято' in result["html"] and 'Вклад принят' not in result["html"]


def test_persona_update_real_handler_sends_cas_revision_and_narrow_envelope():
    result = run_domain_ui("""
      await click({awDomain:'personas'},'shell');
      await click({awDomainAction:'update',awEntity:ids.persona});
      const edit=drawer.innerHTML;
      await submit(form({name:'Changed persona',description:'Kept purpose',style:'Concise',workspace_id:'foreign',role:'owner'}));
      return {edit,html:drawer.innerHTML,posts:calls.filter(call=>call.method==='post')};
    """)
    assert 'value="Owner persona"' in result["edit"]
    assert "Owned description" in result["edit"]
    assert len(result["posts"]) == 1
    post = result["posts"][0]
    assert (post["domain"], post["action"]) == ("personas", "update")
    assert post["body"]["expected_revision"] == 7
    assert post["body"]["payload"] == {"name": "Changed persona", "description": "Kept purpose",
                                       "style": "Concise", "avatar_key": "", "application_role": ""}
    assert post["body"]["idempotency_key"]
    assert "Changed persona" in result["html"]


def test_external_model_task_requires_manual_consent_then_renders_actual_response_evidence():
    result = run_domain_ui("""
      await click({awDomain:'models'},'shell');
      await click({awDomainAction:'task',awEntity:ids.model});
      const shown=drawer.innerHTML;
      await submit(form({rubric_key:'connection_exact'},false));
      const before=calls.filter(call=>call.method==='post').length;
      await submit(form({rubric_key:'connection_exact'},true));
      const resultHtml=drawer.innerHTML;
      await click({awDetailTab:'evaluations'});
      return {shown,before,posts:calls.filter(call=>call.method==='post'),resultHtml,html:drawer.innerHTML};
    """)
    assert 'name="confirmation" required' in result["shown"]
    assert result["before"] == 0
    assert len(result["posts"]) == 1
    assert result["posts"][0]["body"]["payload"] == {"rubric_key": "connection_exact"}
    assert "ACTUAL_RESPONSE" in result["resultHtml"]
    assert "independent_local_evidence_verifier" in result["html"]
    assert "exact_response" in result["html"]
    assert "RESPONSE SHA256" in result["html"]


def test_domain_cancel_task_requires_allowed_action_and_owner_confirmation():
    result = run_domain_ui("""
      await click({awTask:ids.task},'shell');
      const detail=drawer.innerHTML;
      await click({awTaskAction:'cancel'});
      await submit(form({reason:'Stop my queued task'},false));
      const before=calls.filter(call=>call.method==='post').length;
      await submit(form({reason:'Stop my queued task'},true));
      return {detail,before,posts:calls.filter(call=>call.method==='post')};
    """)
    assert 'data-aw-task-action="cancel"' in result["detail"]
    assert 'data-aw-task-action="retry"' not in result["detail"]
    assert result["before"] == 0
    assert len(result["posts"]) == 1
    assert result["posts"][0]["body"]["expected_revision"] == 7
    assert result["posts"][0]["body"]["payload"] == {"reason": "Stop my queued task"}


def test_failed_mutation_retry_keeps_idempotency_key_and_does_not_echo_server_secret():
    result = run_domain_ui("""
      await click({awDomain:'personas'},'shell');
      await click({awDomainAction:'create',awEntity:'new'});
      failPost=true;
      const f=form({name:'Persona with uncertain reply'});
      await submit(f);const message=f.error.textContent;
      await submit(f);
      return {message,posts:calls.filter(call=>call.method==='post')};
    """)
    assert len(result["posts"]) == 2
    assert result["posts"][0]["body"]["idempotency_key"] == result["posts"][1]["body"]["idempotency_key"]
    assert "must-not-render-error-secret" not in result["message"]
    assert "не создаёт дубликат" in result["message"]


def test_system_is_inline_read_only_and_court_sources_are_server_provided():
    result = run_domain_ui("""
      await click({awDomain:'system'},'shell');const system=drawer.innerHTML;
      await click({awDomain:'decisions'},'shell');
      await click({awDomainAction:'create',awEntity:'new'});
      return {system,form:drawer.innerHTML,posts:calls.filter(call=>call.method==='post').length};
    """)
    assert "Real runtime state" in result["system"]
    assert 'data-aw-domain-item="runtime"' not in result["system"]
    assert "must-not-render-system-secret" not in result["system"]
    assert "Stored JSON evidence" in result["form"]
    assert result["posts"] == 0


def test_forged_ui_action_not_granted_by_server_does_not_open_mutation_form():
    result = run_domain_ui("""
      await click({awDomain:'personas'},'shell');const prior=drawer.innerHTML;
      await click({awDomainAction:'activate',awEntity:ids.persona});
      return {unchanged:drawer.innerHTML===prior,posts:calls.filter(call=>call.method==='post').length};
    """)
    assert result == {"unchanged": True, "posts": 0}


def test_owner_binding_requires_server_action_and_selects_only_returned_registry_id():
    result = run_domain_ui("""
      await click({awDomain:'models'},'shell');const ordinary=drawer.innerHTML;
      domains.models.actions.push('bind_existing');
      domains.models.owner_bindings=[{id:'AGT-ABCDEFGHIJKL',name:'Approved Local connection',provider:'openai',model:'existing-model',api_key:'must-not-render-global-secret'}];
      await click({awDomain:'models'},'shell');
      await click({awDomainAction:'bind_existing',awEntity:'new'});
      const shown=drawer.innerHTML;
      await submit(form({registry_id:'AGT-ABCDEFGHIJKL',persona_id:ids.persona,label:'Bound model',api_key:'must-not-send',daily_budget_usd:'999'}));
      return {ordinary,shown,posts:calls.filter(call=>call.method==='post')};
    """)
    assert 'data-aw-domain-action="bind_existing"' not in result["ordinary"]
    assert 'value="AGT-ABCDEFGHIJKL"' in result["shown"]
    assert "Approved Local connection" in result["shown"]
    assert "must-not-render-global-secret" not in result["shown"]
    assert 'name="api_key"' not in result["shown"]
    assert result["posts"][0]["body"]["payload"] == {"registry_id": "AGT-ABCDEFGHIJKL", "persona_id": "11111111-1111-1111-1111-111111111111", "label": "Bound model"}


@pytest.mark.parametrize("identity", ["AGT-x", "../../private", "owner-token", "AGT-ABCDEFGHIJKL?workspace=other", "AGT-abcdefghijkl"])
def test_binding_payload_refuses_noncanonical_registry_identity(identity):
    value = {"registry_id": identity, "persona_id": "11111111-1111-1111-1111-111111111111"}
    assert evaluate(f"(() => {{try {{ui.domainPayload('models','bind_existing',{json.dumps(value)});return false;}}catch (_){{return true;}}}})()") is True


def test_memory_publication_requires_server_action_and_explicit_audience_confirmation():
    result = run_domain_ui("""
      domains.memory.items=[{id:ids.persona,title:'Verified note',status:'active',revision:3,content:'Approved content',actions:['publish_to_workspace']}];
      await click({awDomain:'memory'},'shell');
      await click({awDomainAction:'publish_to_workspace',awEntity:ids.persona});
      const shown=drawer.innerHTML;
      await submit(form({reason:'Share approved lesson'},false));
      const before=calls.filter(call=>call.method==='post').length;
      await submit(form({reason:'Share approved lesson',workspace_id:'foreign',content:'must-not-send'},true));
      return {shown,before,posts:calls.filter(call=>call.method==='post')};
    """)
    assert "участникам этого рабочего пространства" in result["shown"]
    assert "Личный источник сохраняется" in result["shown"]
    assert result["before"] == 0
    assert result["posts"][0]["body"]["payload"] == {"reason": "Share approved lesson"}
    assert result["posts"][0]["body"]["expected_revision"] == 3


def test_consensus_proposal_uses_real_contribution_candidates_without_browser_votes():
    result = run_domain_ui("""
      domains.decisions.actions.push('propose_consensus');
      domains.decisions.contribution_candidates=[{id:ids.persona,title:'Accepted contribution A'},{id:ids.model,title:'Accepted contribution B'}];
      await click({awDomain:'decisions'},'shell');
      await click({awDomainAction:'propose_consensus',awEntity:'new'});
      const shown=drawer.innerHTML;
      await submit(form({title:'Compare accepted inputs',proposal:'Verified proposal',risk:'low',trigger:'requested_review',contribution_ids:[ids.persona,ids.model],votes:[{verdict:'approve'}],workspace_id:'foreign'}));
      return {shown,posts:calls.filter(call=>call.method==='post')};
    """)
    assert "Accepted contribution A" in result["shown"]
    assert "Выбор не создаёт голосов" in result["shown"]
    assert result["posts"][0]["action"] == "propose_consensus"
    assert result["posts"][0]["body"]["payload"] == {
        "title": "Compare accepted inputs", "proposal": "Verified proposal", "risk": "low",
        "trigger": "requested_review", "contribution_ids": ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"],
    }


def test_routine_suggestion_uses_two_verified_outcomes_and_does_not_request_automation():
    result = run_domain_ui("""
      domains.routines.actions.push('suggest_routine');
      domains.routines.outcome_candidates=[{id:ids.persona,title:'Verified outcome A'},{id:ids.model,title:'Verified outcome B'}];
      await click({awDomain:'routines'},'shell');
      await click({awDomainAction:'suggest_routine',awEntity:'new'});
      const shown=drawer.innerHTML;
      await submit(form({title:'Follow up verified work',interval_minutes:'60',outcome_ids:[ids.persona,ids.model],automation_enabled:true}));
      return {shown,posts:calls.filter(call=>call.method==='post')};
    """)
    assert "Verified outcome A" in result["shown"]
    assert "Автоматическое исполнение не включается" in result["shown"]
    assert result["posts"][0]["body"]["payload"] == {
        "title": "Follow up verified work", "interval_minutes": 60,
        "outcome_ids": ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"],
    }


@pytest.mark.parametrize("domain,action,key", [
    ("decisions", "propose_consensus", "contribution_ids"),
    ("routines", "suggest_routine", "outcome_ids"),
])
@pytest.mark.parametrize("identities", [[], ["11111111-1111-1111-1111-111111111111"], ["not-a-uuid", "also-not-a-uuid"]])
def test_derived_proposals_require_two_distinct_canonical_source_records(domain, action, key, identities):
    payload = {"title": "Bounded proposal", "proposal": "Review", "risk": "low", "trigger": "requested_review",
        "interval_minutes": 60, key: identities}
    assert evaluate(f"(() => {{try {{ui.domainPayload('{domain}','{action}',{json.dumps(payload)});return false;}}catch (_){{return true;}}}})()") is True


def test_social_publication_requires_reviewed_snapshot_and_second_explicit_confirmation():
    result = run_domain_ui("""
      await click({awDomain:'publications'},'shell');
      await click({awDomainAction:'prepare',awEntity:'new'});
      const choose=drawer.innerHTML;
      await submit(form({source:'outcome:'+ids.task,raw_response:'must-not-send'}));
      const preview=drawer.innerHTML;
      await submit(form({text:'My reviewed comment',visibility:'followers'},false));
      const before=calls.filter(call=>call.method==='post').length;
      await submit(form({text:'My reviewed comment',visibility:'followers',source_id:ids.persona,source_kind:'memory',approved_snapshot_sha256:'wrong',confirm_permanent:false},true));
      return {choose,preview,before,posts:calls.filter(call=>call.method==='post'),success:drawer.innerHTML};
    """)
    assert "Verified result for review" in result["choose"]
    assert "ПРЕДПРОСМОТР · НЕ ОПУБЛИКОВАНО" in result["preview"]
    assert "&lt;script&gt;snapshot&lt;/script&gt;" in result["preview"]
    assert "<script>" not in result["preview"]
    assert "must-not-render-private-answer" not in result["preview"]
    assert "must-not-render-published-secret" not in result["preview"]
    assert "постоянного снимка" in result["preview"]
    assert result["before"] == 1
    prepare, publish = result["posts"]
    assert prepare["body"]["payload"] == {"source_kind": "outcome", "source_id": "33333333-3333-3333-3333-333333333333"}
    assert publish["action"] == "publish" and publish["id"] == "new"
    assert publish["body"]["expected_revision"] == 7
    assert publish["body"]["payload"] == {"text": "My reviewed comment", "visibility": "followers",
        "source_kind": "outcome", "source_id": "33333333-3333-3333-3333-333333333333",
        "approved_snapshot_sha256": "b" * 64, "confirm_permanent": True}
    assert "ОПУБЛИКОВАНО В SF SOCIAL" in result["success"]
    assert "Мои подписчики" in result["success"] and 'href="community.html"' in result["success"]


@pytest.mark.parametrize("change", [
    {"permanent": False}, {"requires_explicit_confirmation": False}, {"snapshot_sha256": "invalid"},
    {"source_revision": 0}, {"source_revision": 8}, {"snapshot": {"synthetic": True}},
])
def test_invalid_publication_preview_never_opens_publish_form(change):
    result = run_domain_ui("""
      previewOverrides=OVERRIDES;
      await click({awDomain:'publications'},'shell');
      await click({awDomainAction:'prepare',awEntity:'new'});
      const original=form({source:'outcome:'+ids.task});
      await submit(original);
      return {html:drawer.innerHTML,error:original.error.textContent,posts:calls.filter(call=>call.method==='post')};
    """.replace("OVERRIDES", json.dumps(change)))
    assert "постоянного снимка" not in result["html"]
    assert result["error"] and len(result["posts"]) == 1 and result["posts"][0]["action"] == "prepare"


def test_publication_action_cannot_be_opened_without_prepare_even_if_forged_in_collection():
    result = run_domain_ui("""
      domains.publications.actions.push('publish');
      await click({awDomain:'publications'},'shell');const before=drawer.innerHTML;
      await click({awDomainAction:'publish',awEntity:'new'});
      return {unchanged:before===drawer.innerHTML,posts:calls.filter(call=>call.method==='post').length};
    """)
    assert result == {"unchanged": True, "posts": 0}


@pytest.mark.parametrize("source", ["memory:11111111-1111-1111-1111-111111111111", "outcome:garbage", "decision:../../other", "backtest:a?owner=true", "https://external.invalid"])
def test_publication_prepare_does_not_accept_memory_arbitrary_urls_or_invalid_ids(source):
    assert evaluate(f"(() => {{try {{ui.domainPayload('publications','prepare',{{source:{json.dumps(source)}}});return false;}}catch (_){{return true;}}}})()") is True
