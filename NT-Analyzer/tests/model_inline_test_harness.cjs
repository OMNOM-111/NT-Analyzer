/* Actual inline-test handler with a disposable DOM/transport. */
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync('app/static/aurora/assets/pages/ai-command-center.js', 'utf8');
const begin = source.indexOf('    function modelTestControls(');
const end = source.indexOf('    function modelCallButtons(', begin);
const calls = [], box = {innerHTML: '', isConnected: true};
const button = {disabled: false, dataset: {awInlineTest: 'specific-shared-model', awRegistryTest: 'specific-owner-model'},
    closest: () => ({querySelector: () => box})};
let results = [], pendingPost;
const API = {
    aiAgentTest: async id => { calls.push(['registry', id]); return results.shift(); },
    aiControlCenterDomainAction: async (...args) => { calls.push(['post', ...args]); return pendingPost ? await pendingPost : results.shift(); },
    aiControlCenterDomainItem: async (...args) => { calls.push(['get', ...args]); const value = results.shift(); if (value instanceof Error) throw value; return value; },
};
const ctx = {API, signal: undefined, disposed: false, root: {crypto: {randomUUID: () => 'one-request'}},
    domainCache: new Map(), esc: x => String(x), setTimeout: fn => { fn(); }};
vm.createContext(ctx); vm.runInContext(source.slice(begin, end), ctx);
ctx.rows = value => value || [];
vm.runInContext(source.slice(end, source.indexOf('    function modelRows(', end)), ctx);
const multiple = ctx.modelCallButtons([{id:'shared-one', ownership:'shared', actions:['test']}, {id:'shared-two', ownership:'shared', actions:['test']}]);
assert.match(multiple, /Общее подключение 1/); assert.match(multiple, /Общее подключение 2/);
assert.match(multiple, /data-aw-inline-test="shared-one"/); assert.match(multiple, /data-aw-inline-test="shared-two"/);
const shareBegin = source.indexOf('    function shareSection(');
vm.runInContext(source.slice(shareBegin, source.indexOf('    async function toggleShare(', shareBegin)), ctx);
Object.assign(ctx, {count: String, cost: String, date: String});
const sharing = ctx.shareSection([{id:'mine', actions:['unshare'], shared:true}], '', {shared_usage:{by_others:{
    by_caller:[{model_id:'mine', caller_name:'Удалённый пользователь', calls:1, input_tokens:12, output_tokens:3, cost_usd:0.02}],
    recent:[{model_id:'mine', caller_name:'Удалённый пользователь', task:'opaque-task', agent:'deputy', status:'success', input_tokens:12, output_tokens:3, cost_usd:0.02},
        {model_id:'someone-else', task:'foreign-private-reference'}]}}});
assert.match(sharing, /История общих вызовов/); assert.match(sharing, /opaque-task/); assert.match(sharing, /deputy/);
assert.doesNotMatch(sharing, /foreign-private-reference/);
const success = {task: {id: 'test-id', status: 'succeeded'}, evaluation: {passed: true}, actual_model: 'real-version', result_text: 'CONNECTION_OK', synthetic: false};
(async () => {
    let release; pendingPost = new Promise(resolve => {release = resolve;});
    results = [success];
    const running = ctx.testModelInline(button);
    assert.ok(button.disabled); assert.match(box.innerHTML, /Проверяем/);
    await ctx.testModelInline(button); assert.equal(calls.length, 1);
    release({task: {id: 'test-id', status: 'running'}}); await running; pendingPost = null;
    assert.deepEqual(calls.map(c => c.slice(0, 3)), [['post', 'models', 'specific-shared-model'], ['get', 'model_tasks', 'test-id']]);
    assert.match(box.innerHTML, /Модель отвечает, всё работает/); assert.match(box.innerHTML, /<details>/); assert.equal(button.disabled, false);
    assert.equal(ctx.modelTestOutcome({ok: true}).ok, false);
    assert.equal(ctx.modelTestOutcome({ok: true}, true).ok, false);
    assert.equal(ctx.modelTestOutcome({ok: true, response: 'old', application_cache_hit: true}, true).ok, false);
    assert.equal(ctx.modelTestOutcome({...success, synthetic: true}).ok, false);
    assert.equal(ctx.modelTestOutcome({...success, evaluation: {passed: false}}).ok, false);
    // Lost polling response retains the task id. Refresh must GET, never POST again.
    calls.length = 0; results = [{task: {id: 'test-id', status: 'running'}}, new Error('timeout')];
    await ctx.testModelInline(button);
    assert.equal(button.dataset.awTestTask, 'test-id'); assert.match(button.textContent, /Обновить/);
    results = [success]; await ctx.testModelInline(button);
    assert.equal(calls.filter(c => c[0] === 'post').length, 1);
    assert.equal(calls.filter(c => c[0] === 'get').length, 2);
    results = [{ok: false, error: 'model_share_revoked'}]; await ctx.testModelInline(button, true);
    assert.match(box.innerHTML, /Владелец закрыл доступ/); assert.doesNotMatch(box.innerHTML, /всё работает/);
    results = [{ok: true, actual_model: 'specific-owner-model', response: 'CONNECTION_OK', application_cache_hit: false}];
    await ctx.testModelInline(button, true); assert.equal(calls.at(-1)[1], 'specific-owner-model');
    assert.match(box.innerHTML, /Модель отвечает/);
    console.log('PASS');
})().catch(error => {console.error(error); process.exitCode = 1;});
