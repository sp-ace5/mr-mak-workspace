import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import path from 'node:path';
import { mkdir, mkdtemp, readdir, readFile, symlink, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { createFactory } from '../factory.mjs';
import { stub, writeFactoryFixture } from './fixtures/factory-fixture.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');

async function fixture(stubEnv = {}) {
  await mkdir(path.join(repoRoot, '.cache'), { recursive: true });
  const root = await mkdtemp(path.join(repoRoot, '.cache', 'factory-test-'));
  const { factoryDir, env } = await writeFactoryFixture(root);
  const log = env.STUB_LOG;
  Object.assign(process.env, env, stubEnv);
  const factory = createFactory({ factoryDir, repo: root, runner: [process.execPath, [stub]] });
  const server = http.createServer(async (request, response) => {
    try { if (!await factory.handle(request, response, new URL(request.url, 'http://127.0.0.1'))) { response.writeHead(404); response.end(); } }
    catch (error) { response.writeHead(500); response.end(String(error)); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}`;
  const calls = async () => (await readFile(log, 'utf8').catch(() => '')).split('\n').filter(Boolean).map(line => JSON.parse(line));
  return { root, factoryDir, url, calls, close: () => server.close() };
}

async function post(url, body) {
  const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}) });
  const text = await response.text();
  const events = response.headers.get('content-type')?.startsWith('text/event-stream')
    ? text.split('\n\n').filter(frame => frame.startsWith('data: ')).map(frame => JSON.parse(frame.slice(6)))
    : [];
  return { status: response.status, type: response.headers.get('content-type'), events, body: events.length ? null : JSON.parse(text || 'null') };
}

test('packs list reads the fixture DB', async () => {
  const f = await fixture();
  try {
    const response = await fetch(f.url + '/factory/packs');
    assert.equal(response.status, 200);
    const { packs } = await response.json();
    assert.equal(packs[0].pack_id, 'ui_sfx_v1');
    assert.deepEqual(packs[0].counts, { approved: 1, failed: 1, passed: 1 });
    assert.equal(packs[0].blockers, 0);
    assert.equal(packs[0].last_release.target, 'me/ui_sfx_v1');
  } finally { f.close(); }
});

test('pack detail has assets, current gate results, provenance, releases', async () => {
  const f = await fixture();
  try {
    const pack = await (await fetch(f.url + '/factory/packs/ui_sfx_v1')).json();
    assert.equal(pack.assets.length, 3);
    const hover = pack.assets.find(asset => asset.name === 'hover');
    assert.deepEqual(hover.gates.map(gate => gate.passed), [0]);
    assert.equal(pack.provenance.length, 1);
    assert.equal(pack.releases.length, 1);
    assert.equal((await fetch(f.url + '/factory/packs/nope')).status, 404);
    assert.equal((await fetch(f.url + '/factory/packs/UI')).status, 400);
  } finally { f.close(); }
});

test('file route serves build and dist only', async () => {
  const f = await fixture();
  try {
    const file = rel => fetch(f.url + '/factory/file?path=' + encodeURIComponent(rel));
    const listing = await file('dist/ui_sfx_v1/listing.md');
    assert.equal(listing.status, 200);
    assert.equal(await listing.text(), '# UI SFX');
    assert.equal((await file('build/ui_sfx_v1/a.wav')).status, 200);
    for (const rel of ['../secret.txt', 'dist/../../secret.txt', 'dist/..\\..\\secret.txt', path.join(f.root, 'secret.txt'), 'spec/packs/ui_sfx_v1.yaml', 'factory.db', ''])
      assert.equal((await file(rel)).status, 403, rel);
    await symlink(f.root, path.join(f.factoryDir, 'dist/ui_sfx_v1/out'), 'junction');
    assert.equal((await file('dist/ui_sfx_v1/out/secret.txt')).status, 403);
  } finally { f.close(); }
});

const job = (f, cmd, body, id = 'ui_sfx_v1') => post(`${f.url}/factory/packs/${id}/${cmd}`, body);

test('build streams events as SSE and ends with done', async () => {
  const f = await fixture();
  try {
    const result = await job(f, 'build');
    assert.equal(result.status, 200);
    assert.match(result.type, /^text\/event-stream/);
    assert.deepEqual(result.events.find(event => event.msg === 'not json'), { event: 'log', msg: 'not json' });
    assert.deepEqual(result.events.find(event => event.event === 'stderr'), { event: 'stderr', msg: 'warn' });
    assert.deepEqual(result.events.at(-1), { event: 'done', cmd: 'build', exit: 0 });
    assert.deepEqual(await f.calls(), [['build', '--pack', 'spec/packs/ui_sfx_v1.yaml', '--json']]);
  } finally { f.close(); }
});

test('missing done or argparse exit counts as failure', async () => {
  const f = await fixture({ STUB_MODE: 'nodone' });
  try {
    assert.deepEqual((await job(f, 'listing')).events.at(-1), { event: 'done', cmd: 'listing', exit: 1, synthetic: true });
    process.env.STUB_MODE = 'argparse';
    const result = await job(f, 'listing');
    assert.deepEqual(result.events.at(-1), { event: 'done', cmd: 'listing', exit: 2, synthetic: true });
    assert.ok(result.events.some(event => event.event === 'stderr' && event.msg.startsWith('usage:')));
    process.env.STUB_MODE = 'donefail';
    assert.deepEqual((await job(f, 'listing')).events.at(-1), { event: 'done', cmd: 'listing', exit: 3, synthetic: true });
  } finally { f.close(); }
});

test('second job on the same pack returns 409', async () => {
  const f = await fixture({ STUB_MODE: 'slow' });
  try {
    const first = job(f, 'build');
    await new Promise(resolve => setTimeout(resolve, 300));
    assert.equal((await job(f, 'package')).status, 409);
    assert.equal((await first).status, 200);
    assert.equal((await job(f, 'build')).status, 200);
  } finally { f.close(); }
});

test('approve passes names as --only', async () => {
  const f = await fixture();
  try {
    assert.equal((await job(f, 'approve', { names: ['click', 'hover'] })).status, 200);
    assert.deepEqual((await f.calls())[0], ['approve', '--pack', 'spec/packs/ui_sfx_v1.yaml', '--json', '--only', 'click', 'hover']);
    assert.equal((await job(f, 'approve', { names: 'click' })).status, 400);
    assert.equal((await job(f, 'approve', { names: ['-x'] })).status, 400);
    assert.equal((await job(f, 'approve', { names: [] })).status, 400);
    assert.equal((await f.calls()).length, 1);
  } finally { f.close(); }
});

test('publish without matching confirm is rejected', async () => {
  const f = await fixture();
  try {
    for (const body of [{}, { confirm: 'me/other' }, { confirm: 'evil/ui_sfx_v1' }, { confirm: ['me/ui_sfx_v1'] }])
      assert.equal((await job(f, 'publish', body)).status, 400, JSON.stringify(body));
    assert.deepEqual(await f.calls(), []);
    assert.equal((await job(f, 'publish', { confirm: 'me/ui_sfx_v1' })).status, 200);
    assert.equal((await f.calls())[0][0], 'publish');
  } finally { f.close(); }
});

test('missing tool returns 424 with configured path', async () => {
  const f = await fixture();
  try {
    const config = JSON.parse(process.env.STUB_CONFIG);
    const withConfig = change => { process.env.STUB_CONFIG = JSON.stringify(change(structuredClone(config))); };
    withConfig(c => { c.tools.butler = '/no/butler.exe'; return c; });
    let result = await job(f, 'publish', { confirm: 'me/ui_sfx_v1' });
    assert.equal(result.status, 424);
    assert.equal(result.body.tool, 'butler');
    assert.equal(result.body.path, '/no/butler.exe');
    withConfig(c => { c.itch.user = ''; return c; });
    result = await job(f, 'publish', { confirm: '/ui_sfx_v1' });
    assert.equal(result.status, 424);
    assert.equal(result.body.tool, 'itch.user');
    withConfig(c => { c.tools.godot = '/no/godot.exe'; return c; });
    result = await job(f, 'build');
    assert.equal(result.status, 424);
    assert.deepEqual([result.body.tool, result.body.path], ['godot', '/no/godot.exe']);
    withConfig(c => c);
    process.env.STUB_MODE = 'nopython';
    result = await job(f, 'listing');
    assert.equal(result.status, 424);
    assert.equal(result.body.tool, 'python');
    assert.deepEqual(await f.calls(), []);
  } finally { f.close(); }
});

test('unknown pack or command', async () => {
  const f = await fixture();
  try {
    assert.equal((await job(f, 'build', {}, 'nope')).status, 404);
    assert.equal((await job(f, 'init')).status, 404);
    assert.equal((await post(`${f.url}/factory/packs/..%2Fx/build`)).status, 400);
    assert.equal((await job(f, 'build', {}, 'UI')).status, 400);
    assert.deepEqual(await f.calls(), []);
  } finally { f.close(); }
});

test('service requires the bearer token on /factory routes', async () => {
  const { createService } = await import('../server.mjs');
  const repo = await mkdtemp(path.join(repoRoot, '.cache', 'factory-service-'));
  await mkdir(path.join(repo, 'ui')); await mkdir(path.join(repo, 'factory'));
  await writeFile(path.join(repo, 'ui', 'index.html'), '<html></html>');
  const service = await createService({ repo, uiDir: path.join(repo, 'ui') });
  try {
    assert.equal((await fetch(service.origin + '/factory/packs')).status, 401);
    const response = await fetch(service.origin + '/factory/packs', { headers: { Authorization: `Bearer ${service.token}` } });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { packs: [] });
  } finally { await service.close(); }
});

test('publish dry run needs no confirm', async () => {
  const f = await fixture();
  try {
    assert.equal((await job(f, 'publish', { dryRun: 'yes' })).status, 400);
    assert.equal((await job(f, 'build', { dryRun: true })).status, 400);
    assert.deepEqual(await f.calls(), []);
    assert.equal((await job(f, 'publish', { dryRun: true })).status, 200);
    assert.deepEqual((await f.calls()).at(-1), ['publish', '--pack', 'spec/packs/ui_sfx_v1.yaml', '--json', '--dry-run']);
    assert.equal((await job(f, 'publish', { confirm: 'me/ui_sfx_v1', dryRun: false })).status, 200);
    assert.deepEqual((await f.calls()).at(-1), ['publish', '--pack', 'spec/packs/ui_sfx_v1.yaml', '--json']);
  } finally { f.close(); }
});

test('every job writes a log file', async () => {
  const f = await fixture();
  try {
    await job(f, 'build');
    const dir = path.join(f.factoryDir, 'build/ui_sfx_v1/jobs');
    const files = await readdir(dir);
    assert.equal(files.length, 1);
    assert.match(files[0], /^\d{8}-\d{6}-build\.log$/);
    const lines = (await readFile(path.join(dir, files[0]), 'utf8')).trim().split('\n').map(line => JSON.parse(line));
    assert.deepEqual(lines.at(-1), { event: 'done', cmd: 'build', exit: 0 });
    assert.ok(lines.some(line => line.event === 'stderr' && line.msg === 'warn'));
  } finally { f.close(); }
});

test('dry run logs are named apart from real publishes', async () => {
  const f = await fixture();
  try {
    await job(f, 'publish', { dryRun: true });
    assert.match((await readdir(path.join(f.factoryDir, 'build/ui_sfx_v1/jobs')))[0], /-publish-dry-run\.log$/);
  } finally { f.close(); }
});

test('playground runs the CLI without a pack', async () => {
  const f = await fixture({ STUB_MODE: 'ok' });
  try {
    const result = await post(`${f.url}/factory/playground`, { open: true });
    assert.equal(result.status, 200);
    assert.deepEqual(result.events.at(-1), { event: 'done', cmd: 'playground', exit: 0 });
    assert.deepEqual((await f.calls()).at(-1), ['playground', '--json', '--open']);
    assert.equal((await post(`${f.url}/factory/playground`, { open: 'yes' })).status, 400);
    assert.equal((await job(f, 'build', { open: true })).status, 400);
    assert.equal((await job(f, 'playground')).status, 404);                  // not a per-pack command
    assert.equal((await readdir(path.join(f.factoryDir, 'build/_playground/jobs'))).length, 1);

    process.env.STUB_CONFIG = JSON.stringify({ ...JSON.parse(process.env.STUB_CONFIG), tools: { godot: '/no/godot.exe' } });
    const missing = await post(`${f.url}/factory/playground`, {});
    assert.equal(missing.status, 424);
    assert.equal(missing.body.tool, 'godot');
  } finally { f.close(); }
});

test('playground and pack jobs never overlap', async () => {
  const f = await fixture();
  try {
    process.env.STUB_MODE = 'slowplay';
    const first = post(`${f.url}/factory/playground`, {});
    await new Promise(resolve => setTimeout(resolve, 300));
    assert.equal((await post(`${f.url}/factory/playground`, {})).status, 409);
    assert.equal((await job(f, 'build')).status, 409);                      // package may be rewriting dist/
    assert.equal((await first).status, 200);
    process.env.STUB_MODE = 'slow';
    const building = job(f, 'build');
    await new Promise(resolve => setTimeout(resolve, 300));
    assert.equal((await post(`${f.url}/factory/playground`, {})).status, 409);
    assert.equal((await building).status, 200);
  } finally { f.close(); }
});

test('done is the last frame even when stderr arrives after it', async () => {
  const f = await fixture({ STUB_MODE: 'lateerr' });
  try {
    const { events } = await job(f, 'listing');
    assert.ok(events.some(event => event.event === 'stderr' && event.msg === 'late warning'));
    assert.deepEqual(events.at(-1), { event: 'done', cmd: 'listing', exit: 0 });
    assert.equal(events.filter(event => event.event === 'done').length, 1);
  } finally { f.close(); }
});

test('cancel stops a stuck job and its whole process tree', async () => {
  const f = await fixture({ STUB_MODE: 'hang' });
  try {
    assert.equal((await post(`${f.url}/factory/packs/ui_sfx_v1/cancel`)).status, 409);     // nothing running
    const running = job(f, 'build');
    let pid;
    for (let i = 0; i < 50 && !pid; i++) {
      await new Promise(resolve => setTimeout(resolve, 100));
      const logs = await readdir(path.join(f.factoryDir, 'build/ui_sfx_v1/jobs')).catch(() => []);
      const text = logs.length ? await readFile(path.join(f.factoryDir, 'build/ui_sfx_v1/jobs', logs[0]), 'utf8') : '';
      pid = Number(/grandchild (\d+)/.exec(text)?.[1]) || undefined;
    }
    assert.ok(pid, 'stub started its grandchild');
    const cancelled = await post(`${f.url}/factory/packs/ui_sfx_v1/cancel`);
    assert.equal(cancelled.status, 200);
    const { events } = await running;
    assert.ok(events.some(event => event.event === 'cancelled'));
    assert.equal(events.at(-1).event, 'done');
    assert.notEqual(events.at(-1).exit, 0);
    let alive = true;
    for (let i = 0; i < 30 && alive; i++) {
      try { process.kill(pid, 0); await new Promise(resolve => setTimeout(resolve, 100)); } catch { alive = false; }
    }
    assert.equal(alive, false, 'grandchild killed with the job');
    process.env.STUB_MODE = 'ok';
    assert.equal((await job(f, 'build')).status, 200);                                     // lock released
  } finally { f.close(); }
});

test('building a mesh pack also needs Blender', async () => {
  const f = await fixture();
  try {
    const { DatabaseSync } = await import('node:sqlite');
    const db = new DatabaseSync(path.join(f.factoryDir, 'factory.db'));
    db.exec("UPDATE packs SET category = 'mesh' WHERE pack_id = 'ui_sfx_v1'");
    db.close();
    const result = await job(f, 'build');                                   // fixture config has no blender
    assert.equal(result.status, 424);
    assert.equal(result.body.tool, 'blender');
    process.env.STUB_CONFIG = JSON.stringify({ ...JSON.parse(process.env.STUB_CONFIG), tools: { ...JSON.parse(process.env.STUB_CONFIG).tools, blender: path.join(f.root, 'godot.exe') } });
    assert.equal((await job(f, 'build')).status, 200);
    assert.equal((await job(f, 'listing')).status, 200);                    // only build runs Blender
  } finally { f.close(); }
});
