from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "Node.js required for browser script harness")
class TaskLiveLabelTests(unittest.TestCase):
    def run_node(self, script: str) -> None:
        result = subprocess.run(
            [shutil.which("node"), "-e", script, str(ROOT / "public_shell/task.js")],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_local_backend_uses_source_mode_without_guessing_live(self) -> None:
        self.run_node(
            r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');

async function labelFor(sourceMode) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {disabled:true,hidden:false,textContent:'',dataset:{},classList:{toggle(){}},addEventListener(){}});
    return elements.get(id);
  }
  const task = {task_id:'task-label-demo',display_name:'Label demo',district_id:'ntpc-test',action_label:'observe',route_label:'route',eta_band:'none',status:'OPEN',accepted:false,arrived:false,updated_at:'now'};
  const payload = {ok:true,task,task_backend:'local'};
  if (sourceMode !== undefined) payload.source_mode = sourceMode;
  const context = {
    URL, URLSearchParams,
    window:{location:{search:'',pathname:'/tasks/task-label-demo',hash:''}},
    document:{querySelector:element,getElementById:element},
    fetch:async()=>({ok:true,json:async()=>payload})
  };
  vm.runInNewContext(source, context);
  await new Promise(resolve=>setImmediate(resolve));
  return element('runtime-notice').textContent;
}

(async()=>{
  const neutral = await labelFor(undefined);
  if (neutral !== '本機任務帳本；任務明細未提供來源模式。') throw Error('local backend was guessed: ' + neutral);
  if (neutral.includes('LIVE') || neutral.includes('離線')) throw Error('neutral label contains guessed mode');
  const live = await labelFor('LIVE_LOCAL_SANDBOX');
  if (!live.startsWith('LIVE 本機帳本')) throw Error('live label missing: ' + live);
  const offline = await labelFor('SEALED_DEMO_FIXTURE');
  if (!offline.startsWith('離線本機帳本')) throw Error('offline label missing: ' + offline);
})().catch(error=>{console.error(error.message);process.exit(1);});
"""
        )

    def test_open_task_refreshes_from_server_status_without_client_expiry_guess(self) -> None:
        self.run_node(
            r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {disabled:true,hidden:false,textContent:'',dataset:{},classList:{toggle(){}},addEventListener(){}});
  return elements.get(id);
}
const buttons = {
  '[data-event="accept"]': element('accept'),
  '[data-event="arrive"]': element('arrive'),
  '[data-event="complete"]': element('complete'),
  '[data-event="exception"]': element('exception')
};
let task = {task_id:'task-refresh-demo',display_name:'Refresh demo',district_id:'ntpc-test',action_label:'observe',route_label:'route',eta_band:'none',status:'OPEN',accepted:false,arrived:false,updated_at:'now'};
let fetchCount = 0;
let timer = null;
let timerDelay = null;
const windowObject = {
  location:{search:'',pathname:'/tasks/task-refresh-demo',hash:'#expires_at=1'},
  setTimeout(callback, delay){timer = callback; timerDelay = delay; return 1;},
  clearTimeout(){timer = null;}
};
const context = {
  URL, URLSearchParams, window:windowObject,
  document:{querySelector(selector){return buttons[selector];},getElementById:element},
  fetch:async()=>{
    fetchCount += 1;
    return {ok:true,json:async()=>({ok:true,task,task_backend:'local'})};
  }
};
vm.runInNewContext(source, context);
(async()=>{
  await new Promise(resolve=>setImmediate(resolve));
  if (timerDelay !== 15000) throw Error('refresh was inferred from QR grant instead of server contract: ' + timerDelay);
  if (element('status-badge').dataset.status !== 'OPEN') throw Error('client changed OPEN before server did');
  task = {...task,status:'EXPIRED'};
  const refresh = timer;
  timer = null;
  refresh();
  await new Promise(resolve=>setImmediate(resolve));
  if (fetchCount !== 2) throw Error('server detail was not polled exactly once');
  if (element('status-badge').dataset.status !== 'EXPIRED') throw Error('server EXPIRED state was not rendered');
  if (element('status-badge').textContent !== '已失效') throw Error('expired label missing');
  if (!element('task-qr').hidden || !buttons['[data-event="accept"]'].disabled) throw Error('expired controls remain active');
  if (timer !== null) throw Error('expired task kept polling');
})().catch(error=>{console.error(error.message);process.exit(1);});
"""
        )


if __name__ == "__main__":
    unittest.main()
