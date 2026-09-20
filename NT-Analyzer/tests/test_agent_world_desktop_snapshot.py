"""Execute the additive Desktop snapshot command seam without browser or providers.

The fixture extracts real source functions; market-data and ChartEngine behavior
are not replaced in the application. Full live-chart acceptance is separate.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "app" / "static" / "aurora" / "assets" / "pages" / "desktop.js"
SNAPSHOT_ID = "cs_" + "a" * 32


def run_command(options=None):
    script = r"""
const fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync(DESKTOP_PATH,'utf8');
const block = source.slice(source.indexOf('  function waitForBars('), source.indexOf('  let cmdInFlight = false;'));
const opts = OPTIONS;
let clock = 0, fitCalls = 0, captureCalls = 0, apiCalls = 0, request = null, imageOptions = null;
const bars = [0,1,2,3,4].map(index => ({t:`2026-09-04T12:0${index}:00Z`,o:10,h:12,l:9,c:11}));
const snapshot = {id:'SNAPSHOT_ID',file:'SNAPSHOT_ID.jpg',url:'/api/ops/runtime/snapshots/SNAPSHOT_ID.jpg'};
const rec = {model:{id:'window-1',config:{instrument:'MNQ 09-26',timeframe:'5m'}},hasBars:opts.hasBars !== false,
  node:{dataset:{priceMarkerLive:'false',providerConnectionState:'CONNECTED',historyStatus:'external_stale'}},
  _diagnostics:{series_hash:'stored-history-hash'},_transport:'WS',
  chart:{fitView(){fitCalls++;},getData(){return opts.emptyData ? [] : bars;},
    _visibleRange(){return opts.emptyView ? {start:3,end:3} : {start:1,end:4};},
    toImage(config){imageOptions=config;captureCalls++;if(opts.captureThrows)throw new Error('canvas failed');if(opts.largeImage)return 'data:image/png;base64,'+'A'.repeat(350000);return opts.image === undefined ? 'data:image/png;base64,YQ==' : opts.image;}}};
if(opts.unknownMetadata){rec.node.dataset={};rec._diagnostics={};rec._transport=null;bars.forEach(bar=>{bar.t=null;});}
if(opts.noViewportApi)delete rec.chart._visibleRange;
const wins = new Map([['window-1',rec]]);
const context = {API:{http:{async chartSnapshot(body){apiCalls++;request=body;
  if(opts.apiThrows)throw new Error('transport failed');
  if(opts.response !== undefined)return opts.response;
  return {ok:true,command_id:body.command_id,snapshot,report:{ok:true}};
}}},wins,currentConversationId(){return 'legacy-current';},
  ensureWindowForRoot:async()=>rec,ensureAnyWindow:async()=>rec,activeRec:()=>rec,
  bringToFront(){},requestAnimationFrame(fn){if(opts.removeBeforeCapture)wins.clear();fn();},
  setTimeout(fn){clock+=7000;if(opts.barsArrive)rec.hasBars=true;fn();},
  Date:class extends Date {static now(){return clock;}},
};
vm.runInNewContext(block+'\nthis.apply = applyChartCommand;',context);
const cmd = {id:'cc_command-1',type:'snapshot',conversation_id:'conversation-1',payload:{agent_world:opts.agentWorld !== false,fit:opts.fit}};
if(opts.omitCommandId)delete cmd.id;
if(opts.omitConversationId)delete cmd.conversation_id;
(async()=>{
  let result;
  try {result=await context.apply(cmd);} catch(error){result={ok:false,error:error.message};}
  process.stdout.write(JSON.stringify({result,fitCalls,captureCalls,apiCalls,request,imageOptions}));
})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});
""".replace("DESKTOP_PATH", json.dumps(str(DESKTOP))).replace("OPTIONS", json.dumps(options or {})).replace("SNAPSHOT_ID", SNAPSHOT_ID)
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True,
                            text=True, encoding="utf-8", check=True, timeout=20)
    return json.loads(result.stdout)


def test_agent_world_snapshot_preserves_view_and_returns_verified_capture_receipt():
    result = run_command({"fit": True})
    assert result["fitCalls"] == 0
    assert result["captureCalls"] == result["apiCalls"] == 1
    request = result["request"]
    assert request["agent_world"] is True
    assert request["command_id"] == "cc_command-1"
    assert request["mirror_to_telegram"] is False
    assert request["conversation_id"] == "conversation-1"
    assert request["image"] == "data:image/png;base64,YQ=="
    assert result["imageOptions"] == {"type": "image/png", "maxWidth": 1200}
    capture = request["capture"]
    assert capture["surface"] == "desktop_chart"
    assert capture["view_preserved"] is True
    assert capture["instrument"] == "MNQ 09-26"
    assert capture["timeframe"] == "5m"
    assert capture["rendered_bar_count"] == 3
    assert capture["total_bar_count"] == 5
    assert capture["first_bar_time_utc"] == "2026-09-04T12:01:00.000Z"
    assert capture["last_bar_time_utc"] == "2026-09-04T12:03:00.000Z"
    assert capture["price_marker_live"] is False
    assert capture["history_status"] == "external_stale"
    assert capture["provider_connection_state"] == "CONNECTED"
    assert "live" not in capture
    assert result["result"]["snapshot_id"] == SNAPSHOT_ID
    assert result["result"]["snapshot_file"] == SNAPSHOT_ID + ".jpg"
    assert result["result"]["capture"] == capture
    assert result["result"]["report_ok"] is True


def test_unknown_metadata_remains_null_not_fabricated():
    capture = run_command({"unknownMetadata": True})["request"]["capture"]
    for key in ["first_bar_time_utc", "last_bar_time_utc", "series_hash", "price_marker_live", "provider_connection_state", "history_status", "transport"]:
        assert capture[key] is None


@pytest.mark.parametrize("options", [
    {"hasBars": False}, {"emptyData": True}, {"emptyView": True},
    {"noViewportApi": True}, {"removeBeforeCapture": True},
    {"image": ""}, {"image": "data:,"}, {"image": "https://example.com/chart.jpg"},
    {"image": "data:image/jpeg;base64,YQ=="}, {"image": "data:image/webp;base64,YQ=="},
    {"captureThrows": True}, {"omitCommandId": True}, {"omitConversationId": True},
])
def test_missing_bars_capture_or_command_binding_never_calls_snapshot_api(options):
    result = run_command(options)
    assert result["result"]["ok"] is False
    assert result["apiCalls"] == 0
    assert result["fitCalls"] == 0


def test_wait_for_bars_can_finish_before_capture():
    result = run_command({"hasBars": False, "barsArrive": True})
    assert result["result"]["ok"] is True
    assert result["request"]["capture"]["rendered_bar_count"] == 3


@pytest.mark.parametrize("response", [
    None, {}, {"ok": True},
    {"ok": True, "command_id": "other", "snapshot": {"id": SNAPSHOT_ID}, "report": {"ok": True}},
    {"ok": True, "command_id": "cc_command-1", "snapshot": {"id": SNAPSHOT_ID, "file": SNAPSHOT_ID + ".jpg", "url": "https://example.com/chart.jpg"}, "report": {"ok": True}},
    {"ok": True, "command_id": "cc_command-1", "snapshot": {"id": SNAPSHOT_ID, "file": SNAPSHOT_ID + ".jpg", "url": "/api/ops/runtime/snapshots/" + SNAPSHOT_ID + ".jpg"}, "report": {"ok": False}},
    {"ok": True, "command_id": "cc_command-1", "snapshot": {"id": SNAPSHOT_ID, "file": SNAPSHOT_ID + ".jpg", "url": "/api/ops/runtime/snapshots/" + SNAPSHOT_ID + ".jpg"}, "report": {"ok": "true"}},
])
def test_http_success_without_matching_saved_snapshot_and_chat_receipt_is_failure(response):
    result = run_command({"response": response})
    assert result["result"]["ok"] is False
    assert result["apiCalls"] == 1
    assert "snapshot_id" not in result["result"]


def test_transport_failure_is_not_successful_capture():
    assert run_command({"apiThrows": True})["result"]["ok"] is False


def test_agent_world_png_limit_fails_before_network_with_owner_actionable_message():
    result = run_command({"largeImage": True})
    assert result["result"]["ok"] is False
    assert "256 KiB" in result["result"]["error"]
    assert result["apiCalls"] == 0


@pytest.mark.parametrize("fit,expected", [(None, 1), (True, 1), (False, 0)])
def test_legacy_snapshot_keeps_existing_fit_request_and_ack_contract(fit, expected):
    result = run_command({"agentWorld": False, "fit": fit, "response": {"ok": True}})
    assert result["fitCalls"] == expected
    assert result["imageOptions"] == {"maxWidth": 1600, "quality": 0.9}
    assert result["result"] == {"ok": True, "window_id": "window-1"}
    assert set(result["request"]) == {"image", "conversation_id", "instrument", "timeframe", "outcome", "text", "caption"}


def test_command_poller_maps_capture_errors_to_failed_ack():
    source = DESKTOP.read_text(encoding="utf-8")
    poller = source.split("  let cmdInFlight = false;", 1)[1].split("// ---- proportional chart grids", 1)[0]
    assert "if (!result || result.ok === false) status = 'failed'" in poller
    assert "catch (e) { result = { ok: false, error:" in poller
    assert "status = 'failed';" in poller
    assert "API.http.ackChartCommand(cmd.id, status, result)" in poller
