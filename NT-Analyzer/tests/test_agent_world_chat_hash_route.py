"""Execute the actual same-page SF Chat route handlers without a page reload."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_same_page_chat_link_opens_one_form_and_preserves_source():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    root = Path(__file__).resolve().parents[1]
    script = r"""
const fs=require('fs'), vm=require('vm'), assert=require('assert');
const ui=fs.readFileSync('app/static/aurora/assets/ui.js','utf8');
const page=fs.readFileSync('app/static/aurora/assets/pages/ai-command-center.js','utf8');
const handlers=new Map(), calls=[], forms=[], leaves=[];
let closed=0, prevented=0;
const location={href:'http://localhost:8815/ui/ai-command-center.html',origin:'http://localhost:8815',pathname:'/ui/ai-command-center.html',hash:'#tab=overview'};
const browser={location,crypto:{randomUUID:()=> 'request-random'},addEventListener:(n,f)=>handlers.set(n,f),removeEventListener:(n)=>handlers.delete(n),dispatchEvent:e=>handlers.get(e.type)?.()};
const context={URL, URLSearchParams, Event, JSON, root:browser,window:browser,disposed:false,mutationBusy:false,detailGeneration:0,overview:{enabled:true},
 UI:{closeOrchestrator:()=>closed++,onLeave:f=>leaves.push(f)}, closeOrchestrator:()=>closed++,
 openDomain:async d=>{context.detailGeneration++;calls.push(['domain',d]);},
 API:{aiControlCenterDomainAction:async(d,id,a,b)=>{calls.push([a,b.payload]);return {goal:'Проверь мои числа',chat_source:b.payload};}},
 openDomainAction:async(a,id,t,seed)=>forms.push(seed),openDrawer:()=>assert.fail('Unexpected error'),readError:String};
vm.createContext(context);
vm.runInContext(ui.slice(ui.indexOf('  function orchFollowAgentWorldLink('),ui.indexOf('  function orchActionsHtml(')),context);
vm.runInContext(page.slice(page.indexOf('    let chatRouteGeneration ='),page.indexOf('    const linkedTask =')),context);
const href=location.href+'#tab=overview&domain=automation&chat_conversation=default&chat_message=MSG-SOURCE';
const click=()=>context.orchFollowAgentWorldLink({target:{closest:()=>({href})},button:0,preventDefault:()=>prevented++});
(async()=>{
 click(); assert.equal(prevented,1);assert.equal(closed,1);assert(location.hash.includes('MSG-SOURCE'));
 browser.dispatchEvent(new Event('hashchange')); // Browser's same-document navigation.
 browser.dispatchEvent(new Event('hashchange')); // In-flight duplicate must not double-open.
 await new Promise(setImmediate);
 assert.equal(forms.length,1);assert.equal(forms[0].goal,'Проверь мои числа');
 assert.deepEqual(calls[1],['chat_seed',{conversation_id:'default',source_message_id:'MSG-SOURCE'}]);
 click(); await new Promise(setImmediate); // Same hash can intentionally reopen after closing.
 assert.equal(forms.length,2);assert.equal(prevented,2);
 location.hash='#tab=agents&domain=models';browser.dispatchEvent(new Event('hashchange'));
 await new Promise(setImmediate);assert.equal(forms.length,2);
 let resume;
 context.API.aiControlCenterDomainAction=()=>new Promise(resolve=>resume=resolve);
 click();browser.dispatchEvent(new Event('hashchange'));await new Promise(setImmediate);
 context.detailGeneration++; // User closes/cancels the drawer before seed arrives.
 resume({goal:'must not reopen'});await new Promise(setImmediate);assert.equal(forms.length,2);
 leaves.forEach(f=>f());assert(!handlers.has('hashchange'));assert(!handlers.has('aw-chat-navigate'));
 assert(!ui.slice(ui.indexOf('  function orchFollowAgentWorldLink('),ui.indexOf('  function orchActionsHtml(')).includes('reload'));
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result = subprocess.run([node, "-e", script], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
