"""Large history stays inert; only explicitly played speech owns a decoder."""
import json
import subprocess
from pathlib import Path


def test_history_faces_defer_and_release_media_without_losing_the_avatar():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app/static/aurora/assets/ui.js').read_text(encoding='utf-8')
    def function(name):
        return 'function ' + name + '(' + source.split('function ' + name + '(', 1)[1].split('\n  function ', 1)[0]
    script = '''
const assert = require('node:assert/strict');
const esc = String, agentAvatarId = () => 'vitek', agentAvatarUrl = () => 'assets/agents/vitek/speaking.webm';
const AGENT_FACE_CROP = {vitek: {zoom:2.5,cx:50,cy:34.53}}, agentFaceReduceMotion = () => false;
''' + '\n'.join(function(n) for n in ('agentFacePause', 'agentFacePlay', 'agentAvatarHtml')) + '''
const rows = Array.from({length:200}, (_,i) => agentAvatarHtml('vitek', {cls:'orch-msg-face',messageId:String(i)})).join('');
assert.equal((rows.match(/poster=/g)||[]).length, 200);
assert.equal((rows.match(/<video src=/g)||[]).length, 0);
assert.equal((rows.match(/preload="none"/g)||[]).length, 200);
let loads=0, plays=0, pauses=0, source=null;
const handlers={}, classes=new Set();
const video={dataset:{deferredSrc:'assets/agents/vitek/speaking.webm'},readyState:0,
 hasAttribute:()=>source!==null, set src(v){source=v}, removeAttribute(){source=null},
 load(){loads++}, pause(){pauses++}, play(){plays++;return Promise.resolve()},
 addEventListener(name,fn){handlers[name]=fn}};
const face={isConnected:true,querySelector:()=>video,classList:{add:v=>classes.add(v),remove:v=>classes.delete(v),contains:v=>classes.has(v)}};
agentFacePlay(face,{loop:true});
assert.equal(source,video.dataset.deferredSrc); assert.equal(loads,1); assert.equal(plays,0);
handlers.loadeddata(); assert.equal(plays,1);
agentFacePause(face); assert.equal(source,null); assert.equal(loads,2); assert.equal(pauses,1);
assert.equal(classes.has('playing'),false);
// Ordinary agent cards retain their existing animated presentation.
assert.match(agentAvatarHtml('vitek',{cls:'sm'}), /<video src=/);
console.log(JSON.stringify({history:200,decodersBeforeSpeech:0}));
'''
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['decodersBeforeSpeech'] == 0
    for name in ('vitek','manager','marina','tolik','nikita','ivan'):
        assert (root / f'app/static/aurora/assets/agents/{name}/poster.png').is_file()
