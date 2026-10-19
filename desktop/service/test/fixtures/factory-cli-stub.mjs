// Stands in for `node scripts/run-python.mjs ...` in factory tests: never runs
// Python, butler, approve or publish. Records its arguments in $STUB_LOG.
import { appendFileSync } from 'node:fs';

const args = process.argv.slice(2);
const mode = process.env.STUB_MODE || 'ok';
const out = value => process.stdout.write((typeof value === 'string' ? value : JSON.stringify(value)) + '\n');
if (mode === 'nopython') { process.stderr.write('Python 3 not found. Tried: py -3\n'); process.exit(1); }
if (args[0] === '-c') { if (mode === 'slowconfig') await new Promise(resolve => setTimeout(resolve, 800)); out(process.env.STUB_CONFIG); process.exit(0); }
const [, cmd, ...rest] = args;   // args[0] is run.py
appendFileSync(process.env.STUB_LOG, JSON.stringify([cmd, ...rest]) + '\n');
if (mode === 'argparse') { process.stderr.write('usage: run.py [-h] {new,...}\n'); process.exit(2); }
if (mode === 'nodone') { out({ event: 'log', msg: 'hi' }); process.exit(0); }
if (mode === 'donefail') { out({ event: 'done', cmd, exit: 0 }); process.exit(3); }
if (mode === 'lateerr') { out({ event: 'done', cmd, exit: 0 }); await new Promise(resolve => setTimeout(resolve, 150)); process.stderr.write('late warning\n'); process.exit(0); }
if (mode === 'hang') {   // a stuck CLI with a child of its own, like run-python.mjs -> python
  const { spawn } = await import('node:child_process');
  const kid = spawn(process.execPath, ['-e', 'setTimeout(() => {}, 60000)'], { stdio: 'ignore' });
  out({ event: 'log', msg: `grandchild ${kid.pid}` });
  await new Promise(resolve => setTimeout(resolve, 60000));
}
if (cmd === 'playground') {
  if (mode === 'slowplay') await new Promise(resolve => setTimeout(resolve, 800));
  out({ event: 'playground', msg: 'playground: 1 approved, packaged pack(s)', packs: ['ui_sfx_v1'] });
  out({ event: 'check', msg: 'playground loads: 0 shaders, 4 sounds', shaders: 0, sounds: 4 });
  if (rest.includes('--open')) out({ event: 'opened', msg: 'opened playground', path: 'playground' });
  out({ event: 'done', cmd, exit: 0 });
  process.exit(0);
}
if (cmd === 'publish') {
  const pack = rest[rest.indexOf('--pack') + 1].replace(/^spec\/packs\/|\.yaml$/g, '');
  const user = JSON.parse(process.env.STUB_CONFIG).itch.user;
  if (mode === 'refused') { out({ event: 'refused', msg: 'PUBLISH REFUSED: not approved: hover', reason: 'not approved: hover' }); out({ event: 'done', cmd, exit: 1 }); process.exit(1); }
  const dry = rest.includes('--dry-run');
  for (const channel of ['godot-addon', 'html5']) {
    const target = `${user}/${pack}:${channel}`;
    out({ event: 'push', msg: `${dry ? 'DRY RUN  ' : ''}butler push x ${target}`, channel, target, dry_run: dry, sha256: (channel === 'html5' ? 'b' : 'a').repeat(64) });
    if (dry) continue;
    if (mode === 'nologin') { out({ event: 'error', msg: `butler push failed (1) for ${target}`, message: 'Please run butler login first', channel }); out({ event: 'done', cmd, exit: 1 }); process.exit(1); }
    out({ event: 'pushed', msg: `pushed ${target}`, channel, target });
  }
  out({ event: 'done', cmd, exit: 0 });
  process.exit(0);
}
if (mode === 'slow') await new Promise(resolve => setTimeout(resolve, 800));
out({ event: 'log', msg: 'hi' });
out('not json');
process.stderr.write('warn\n');
out({ event: 'done', cmd, exit: 0 });
