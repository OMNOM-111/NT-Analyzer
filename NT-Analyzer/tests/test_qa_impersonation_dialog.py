"""Exercise the shipped QA handler without native browser dialogs or real sessions."""
import json
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize("mode", ["accept", "cancel", "detached", "api_error", "duplicate"])
def test_qa_impersonation_awaits_app_confirmation(mode):
    source = (Path(__file__).resolve().parents[1] / "app/static/aurora/assets/ui.js").read_text(encoding="utf-8")
    handler = source.split("qsa('[data-stg-as]', node).forEach(btn => btn.onclick = async () => {", 1)[1].split("\n      });", 1)[0]
    script = r'''
const assert = require('node:assert/strict');
const input = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const btn = {disabled:false, isConnected:input.mode!=='detached', dataset:{stgAs:'991881402'}};
let resolveDialog, calls=[], errors=[], reloads=0;
const confirmDialog=()=>new Promise(resolve=>{resolveDialog=resolve;});
const confirm=()=>{throw Error('native dialog forbidden');};
const API={http:{ownerImpersonate:async id=>{calls.push(id); if(input.mode==='api_error') throw Error('denied');}}};
const toast=()=>{}, reportError=e=>errors.push(e.message), setTimeout=fn=>fn(), location={reload:()=>reloads++};
const run=new Function('btn','confirmDialog','confirm','API','toast','reportError','setTimeout','location',
  'return (async()=>{'+input.handler+'})();');
const invoke=()=>run(btn,confirmDialog,confirm,API,toast,reportError,setTimeout,location);
(async()=>{
  const pending=invoke(); assert.equal(btn.disabled,true); assert.equal(calls.length,0);
  if(input.mode==='duplicate') await invoke();
  resolveDialog(input.mode!=='cancel'); await pending;
  const dispatch=!['cancel','detached'].includes(input.mode);
  assert.deepEqual(calls,dispatch?[991881402]:[]);
  assert.equal(reloads,dispatch&&input.mode!=='api_error'?1:0);
  assert.deepEqual(errors,input.mode==='api_error'?['denied']:[]);
  if(['cancel','api_error'].includes(input.mode)) assert.equal(btn.disabled,false);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result = subprocess.run(["node", "-e", script], input=json.dumps({"mode": mode, "handler": handler}),
        text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_qa_drawer_offset_tracks_actual_banner_height_and_resets():
    assets = Path(__file__).resolve().parents[1] / "app/static/aurora/assets"
    source = (assets / "ui.js").read_text(encoding="utf-8")
    helper = source.split("function syncImpersonationLayout() {", 1)[1].split("\n  }", 1)[0]
    script = r'''
const assert=require('node:assert/strict');
const helper=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
let bottom=45, present=true, value;
const qs=()=>present?{getBoundingClientRect:()=>({bottom})}:null;
const document={body:{style:{setProperty:(key,v)=>{assert.equal(key,'--qa-drawer-top');value=v;}}}};
const sync=new Function('qs','document',helper);
sync(qs,document); assert.equal(value,'45px');
bottom=91.3; sync(qs,document); assert.equal(value,'92px');
present=false; sync(qs,document); assert.equal(value,'0px');
'''
    result = subprocess.run(["node", "-e", script], input=json.dumps(helper), text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    banner = source.split("function renderImpersonationBanner(auth) {", 1)[1].split("\n  }", 1)[0]
    assert "new ResizeObserver(syncImpersonationLayout)" in banner
    assert "observer.observe(bar)" in banner and "observer.disconnect()" in banner
    assert "window.removeEventListener('resize', syncImpersonationLayout)" in banner
    css = (assets / "theme.css").read_text(encoding="utf-8")
    drawer = css.split(".drawer {", 1)[1].split("}", 1)[0]
    assert "top: var(--qa-drawer-top, 0px)" in drawer
    assert "height: calc(100vh - var(--qa-drawer-top, 0px))" in drawer
