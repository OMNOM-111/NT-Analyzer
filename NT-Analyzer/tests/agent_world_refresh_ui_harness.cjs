'use strict';
// Execute shipped refresh/navigation handlers against a disposable DOM/API port.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/static/aurora/assets/pages/ai-command-center.js'), 'utf8');
const mode = process.argv[2];
function extract(name) {
  const start = source.search(new RegExp('^    (?:async )?function ' + name + '\\(', 'm'));
  assert.ok(start >= 0, 'shipped handler exists: ' + name);
  const rest = source.slice(start + 1), next = rest.search(/\n    (?:(?:async )?function |const recordId)/);
  return source.slice(start, next < 0 ? undefined : start + 1 + next);
}
const calls = [], button = {disabled:false}, scope = {workspace_id:'ws_refresh', user_uuid:'one', environment:'development'};
const content = {innerHTML:'preserved', setAttribute(){}, contains: () => false};
const drawer = {open:true, classList:{contains:()=>drawer.open}, querySelector:()=>true};
const env = {
  disposed:false, refreshing:false, quietDrawer:false, mutationBusy:false, actionForm:null, demoBusy:false, pendingListReads:0,
  generation:0, overviewGeneration:0, detailGeneration:0, detailKind:'', detailTab:'summary', detail:null, profile:null, domainState:null,
  currentDrawer:null, returnFocus:null, tab:'work', TABS:['overview','work','agents'], shell:{},
  workRows:[], nextCursor:null, demoKey:null, query:'', filter:'all', signal:undefined, content,
  overview:{enabled:true,scope,stats:{active_tasks:1},tasks:[{id:'task',display_status:'running'}]},
  personaAudio:{activePersona:()=>false}, document:{hidden:false,activeElement:{}},
  root:{getSelection:()=>({isCollapsed:true}),history:{replaceState(){}}},
  qs:()=>button, qsa:()=>[], taskId:t=>t?.id || '', agentId:a=>a?.id || '',
  stopPersonaAudio:()=>calls.push('audio-stop'), refreshFaces:()=>{},
  renderHeader:()=>calls.push(['header',env.overview?.stats.active_tasks]),
  renderWork:()=>calls.push(['work',env.workRows.map(t=>t.display_status)]),
  renderOverview:()=>calls.push('overview'), renderAgents:()=>calls.push('agents'),
  drawTask:()=>calls.push(['task',env.detail.display_status,env.quietDrawer]),
  openProfile:()=>calls.push(['profile',env.quietDrawer]),
  empty:()=>'', items:r=>r.items, rows:v=>Array.isArray(v)?v:[],
  UI:{closeDrawer:()=>{drawer.open=false;calls.push('close');}},
  API:{
    aiControlCenterOverview:async()=>{calls.push('read-overview'); return {enabled:true,scope,stats:{active_tasks:0},agents:[{id:'agent'}],tasks:[{id:'task',display_status:'awaiting_review'}]};},
    aiControlCenterTasks:async()=>{calls.push('read-work');return {items:[{id:'task',display_status:'awaiting_review'}]};},
    aiControlCenterTask:async()=>{calls.push('read-task');return {id:'task',display_status:'awaiting_review'};},
  },
};
vm.createContext(env);
['selectTab','backgroundReadBlocked','preserveView','readWorkPages','loadTab','refresh','readError','openDrawer'].forEach(name=>vm.runInContext(extract(name),env));
(async()=>{
  if (mode === 'navigation') {
    await env.selectTab('work',true);
    assert.ok(calls.includes('read-overview') && calls.includes('read-work'));
    assert.deepEqual(calls.find(c=>Array.isArray(c)&&c[0]==='header'),['header',0]);
    assert.deepEqual(JSON.parse(JSON.stringify(calls.find(c=>Array.isArray(c)&&c[0]==='work'))),['work',['awaiting_review']]);
  } else if (['form','hidden','audio','selection','search','singleflight','disposed'].includes(mode)) {
    if (mode==='form') env.actionForm={id:'pending-consent'};
    if (mode==='hidden') env.document.hidden=true;
    if (mode==='audio') env.personaAudio.activePersona=()=>true;
    if (mode==='selection') env.root.getSelection=()=>({isCollapsed:false});
    if (mode==='search') {content.contains=()=>true;env.document.activeElement={tagName:'INPUT'};}
    if (mode==='singleflight') env.refreshing=true;
    if (mode==='disposed') env.disposed=true;
    await env.refresh({background:true});
    assert.deepEqual(calls,[]); assert.equal(content.innerHTML,'preserved');
  } else if (mode==='task' || mode==='profile') {
    env.currentDrawer=drawer; env.detailKind=mode==='task'?'task':'agent';
    env.detail={id:'task',display_status:'running'};env.profile={id:'agent'};
    await env.refresh({background:true});
    assert.ok(!calls.includes('audio-stop'));
    assert.deepEqual(calls.find(c=>Array.isArray(c)&&c[0]===mode),mode==='task'?['task','awaiting_review',true]:['profile',true]);
    assert.equal(env.quietDrawer,false);
  } else if (mode==='profile-removed') {
    env.currentDrawer=drawer;env.detailKind='agent';env.profile={id:'removed'};
    await env.refresh({background:true});
    assert.equal(env.profile,null);assert.ok(calls.includes('close'));
  } else if (mode.startsWith('late-form-')) {
    env.currentDrawer=drawer;
    env.API.aiControlCenterOverview=async()=>{env.actionForm={id:'new-consent',text:'keep'};++env.detailGeneration;
      if (mode!=='late-form-success') throw {status:mode==='late-form-denied'?403:500};
      return {enabled:true,scope,stats:{active_tasks:0}};};
    await env.refresh({background:true});
    if (mode==='late-form-denied') {assert.equal(env.actionForm,null);assert.ok(calls.includes('close'));}
    else {assert.equal(env.actionForm.text,'keep');assert.ok(!calls.includes('close'));assert.equal(content.innerHTML,'preserved');}
  } else if (mode==='late-search' || mode==='late-selection') {
    env.API.aiControlCenterTasks=async()=>{
      if (mode==='late-search') {content.contains=()=>true;env.document.activeElement={tagName:'INPUT'};}
      else env.root.getSelection=()=>({isCollapsed:false});
      return {items:[{id:'updated'}]};};
    await env.refresh({background:true});
    assert.equal(content.innerHTML,'preserved');assert.ok(!calls.some(c=>Array.isArray(c)&&c[0]==='work'));
    assert.equal(env.overview.stats.active_tasks,1);assert.equal(env.pendingListReads,0);
  } else if (mode==='pages' || mode==='cursor-cycle') {
    env.workRows=Array.from({length:100},(_,id)=>({id:String(id)}));let page=0;
    env.API.aiControlCenterTasks=async query=>{calls.push(['page',query.cursor]);return {items:Array.from({length:50},(_,n)=>({id:String(page*50+n)})),next_cursor:mode==='cursor-cycle'?'same':++page===1?'next':'last'};};
    await env.refresh({background:true});
    assert.equal(env.workRows.length,100);assert.equal(env.pendingListReads,0);
    if (mode==='pages') {assert.equal(env.nextCursor,'last');assert.deepEqual(calls.filter(c=>Array.isArray(c)&&c[0]==='page'),[['page',''],['page','next']]);}
    else {assert.equal(env.nextCursor,null);assert.match(button.textContent,/ранее загруженные/);}
  } else if (mode==='quiet-drawer-focus') {
    const old={isConnected:true,hasAttribute:k=>k==='data-aw-task-action',getAttribute:k=>k==='data-aw-task-action'?'review':null};
    const replacement={getAttribute:k=>k==='data-aw-task-action'?'review':null,focus:()=>calls.push('restored-focus')};
    let replaced=false;const body={scrollTop:42,scrollLeft:7,contains:el=>el===old,set innerHTML(_v){replaced=true;old.isConnected=false;this.scrollTop=0;this.scrollLeft=0;}};
    const heading={};drawer.setAttribute=()=>{};drawer.style={width:'650px'};
    env.currentDrawer=drawer;env.quietDrawer=true;env.document.activeElement=old;
    env.qs=(selector)=>selector==='.drawer-b'?body:heading;
    env.qsa=selector=>selector==='button, a, [tabindex]'&&replaced?[replacement]:[];
    env.openDrawer('Same task','Updated result');
    assert.equal(body.scrollTop,42);assert.equal(body.scrollLeft,7);assert.equal(drawer.style.width,'650px');
    assert.ok(calls.includes('restored-focus'));assert.ok(!calls.includes('audio-stop'));
  } else if (mode==='closed-while-reading' || mode==='selection-while-reading-task') {
    env.currentDrawer=drawer;env.detailKind='task';env.detail={id:'task',display_status:'running'};
    env.API.aiControlCenterTask=async()=>{if(mode==='closed-while-reading'){drawer.open=false;++env.detailGeneration;}else env.root.getSelection=()=>({isCollapsed:false});return {id:'task',display_status:'awaiting_review'};};
    await env.refresh({background:true});
    assert.ok(!calls.some(c=>Array.isArray(c)&&c[0]==='task'));
  } else if (mode==='scope-change') {
    env.currentDrawer=drawer;env.detailKind='task';env.detail={id:'task',display_status:'running'};
    env.API.aiControlCenterOverview=async()=>({enabled:true,scope:{...scope,workspace_id:'ws_other'},stats:{active_tasks:0}});
    await env.refresh({background:true});
    assert.equal(env.detail,null);assert.ok(calls.includes('close'));assert.ok(!calls.includes('read-task'));
  } else if (mode==='read-denied') {
    env.currentDrawer=drawer;
    env.API.aiControlCenterOverview=async()=>{throw {status:403};};
    await env.refresh({background:true});
    assert.equal(env.overview,null);assert.ok(calls.includes('close'));assert.equal(env.refreshing,false);
  } else throw Error('unknown case');
  assert.ok(!calls.some(c=>typeof c==='string'&&/enqueue|approve|retry|write/.test(c)));
  process.stdout.write(JSON.stringify({ok:true,mode}));
})().catch(error=>{console.error(error);process.exitCode=1;});
