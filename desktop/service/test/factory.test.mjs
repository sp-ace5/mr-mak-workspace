import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import path from 'node:path';
import { mkdir, mkdtemp, readFile, symlink, writeFile } from 'node:fs/promises';
import { DatabaseSync } from 'node:sqlite';
import { fileURLToPath } from 'node:url';
import { createFactory } from '../factory.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const stub = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures', 'factory-cli-stub.mjs');

// A temp factory/ with a fixture DB, build/dist files, one pack spec, and a
// secret file beside factory/ that no route may ever serve.
async function fixture(stubEnv = {}) {
  await mkdir(path.join(repoRoot, '.cache'), { recursive: true });
  const root = await mkdtemp(path.join(repoRoot, '.cache', 'factory-test-'));
  const factoryDir = path.join(root, 'factory');
  for (const dir of ['dist/ui_sfx_v1', 'build/ui_sfx_v1', 'spec/packs']) await mkdir(path.join(factoryDir, dir), { recursive: true });
  await writeFile(path.join(root, 'secret.txt'), 'secret');
  await writeFile(path.join(factoryDir, 'dist/ui_sfx_v1/listing.md'), '# UI SFX');
  await writeFile(path.join(factoryDir, 'build/ui_sfx_v1/a.wav'), 'RIFF');
  await writeFile(path.join(factoryDir, 'spec/packs/ui_sfx_v1.yaml'), 'pack_id: ui_sfx_v1\n');
  await writeFile(path.join(root, 'godot.exe'), '');
  await writeFile(path.join(root, 'butler.exe'), '');
  const db = new DatabaseSync(path.join(factoryDir, 'factory.db'));
  db.exec(await readFile(path.join(repoRoot, 'factory/pipeline/schema.sql'), 'utf8'));
  db.exec(`
    INSERT INTO packs (pack_id, category, spec_path, spec_hash) VALUES ('ui_sfx_v1', 'audio', 'spec/packs/ui_sfx_v1.yaml', 'h1');
    INSERT INTO licenses (license_id, commercial_ok, checked_on) VALUES ('own-work', 1, '2026-10-18');
    INSERT INTO assets (asset_id, pack_id, kind, name, status, attempts, run_id) VALUES
      ('ui_sfx_v1/click', 'ui_sfx_v1', 'ui_sfx', 'click', 'approved', 1, 'r1'),
      ('ui_sfx_v1/hover', 'ui_sfx_v1', 'ui_sfx', 'hover', 'failed', 2, 'r2');
    INSERT INTO gate_results (asset_id, attempt, recipe, gate, passed, measured, expected) VALUES
      ('ui_sfx_v1/hover', 1, 'h1', 'peak', 1, '-3', '<=-1'),
      ('ui_sfx_v1/hover', 2, 'h1', 'peak', 0, '0', '<=-1'),
      ('ui_sfx_v1/hover', 2, 'old', 'peak', 1, '-3', '<=-1');
    INSERT INTO provenance (asset_id, run_id, step, tool, license_id, ai_generated) VALUES
      ('ui_sfx_v1/click', 'r1', 'synth', 'factory.sfx_ui', 'own-work', 0),
      ('ui_sfx_v1/click', 'old', 'synth', 'factory.sfx_ui', 'own-work', 0);
    INSERT INTO releases (pack_id, channel, target, file_sha256, spec_hash) VALUES ('ui_sfx_v1', 'godot-addon', 'me/ui_sfx_v1', 'abc', 'h1');
  `);
  db.close();
  const config = { tools: { godot: path.join(root, 'godot.exe'), butler: path.join(root, 'butler.exe') }, itch: { user: 'me' } };
  const log = path.join(root, 'stub.log');
  Object.assign(process.env, { STUB_LOG: log, STUB_MODE: 'ok', STUB_CONFIG: JSON.stringify(config) }, stubEnv);
  const factory = createFactory({ factoryDir, repo: root, runner: [process.execPath, [stub]] });
  const server = http.createServer(async (request, response) => {
    try { if (!await factory.handle(request, response, new URL(request.url, 'http://127.0.0.1'))) { response.writeHead(404); response.end(); } }
    catch (error) { response.writeHead(500); response.end(String(error)); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}`;
  const calls = async () => (await readFile(log, 'utf8').catch(() => '')).split('\n').filter(Boolean).map(line => JSON.parse(line));
  return { root, factoryDir, url, calls, close: () => { factory.close(); server.close(); } };
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
    assert.deepEqual(packs[0].counts, { approved: 1, failed: 1 });
    assert.equal(packs[0].blockers, 0);
    assert.equal(packs[0].last_release.target, 'me/ui_sfx_v1');
  } finally { f.close(); }
});

test('pack detail has assets, current gate results, provenance, releases', async () => {
  const f = await fixture();
  try {
    const pack = await (await fetch(f.url + '/factory/packs/ui_sfx_v1')).json();
    assert.equal(pack.assets.length, 2);
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
