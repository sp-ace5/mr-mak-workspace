import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, mkdtemp, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { WebSocket } from 'ws';
import { createService } from '../server.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');

test('a chat draft from the Workspace window reaches the Chats window and is never sent', async () => {
  await mkdir(path.join(root, '.cache'), { recursive: true });
  const repo = await mkdtemp(path.join(root, '.cache', 'chat-draft-'));
  await mkdir(path.join(repo, 'ui'));
  await writeFile(path.join(repo, 'ui', 'index.html'), '<html></html>');
  const service = await createService({ repo, uiDir: path.join(repo, 'ui'), mcpOptions: { home: path.join(repo, 'fake-home'), env: {} } });
  const written = [];
  const session = service.sessions.make({ id: 'draft-chat', name: 'Draft fixture', agent: 'codex', cwd: repo, status: 'running', open: true, cols: 80, rows: 30 });
  service.sessions.items.set(session.id, session); await service.sessions.hydrate(session);
  session.process = { write: data => written.push(data), resize() {}, kill() {} };
  const draft = (body, headers = { Authorization: `Bearer ${service.token}` }) =>
    fetch(service.origin + '/api/chats/draft', { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const ws = new WebSocket(service.origin.replace('http:', 'ws:') + '/events', { headers: { Origin: service.origin } });
  const events = [];
  try {
    await new Promise((resolve, reject) => { ws.once('open', resolve); ws.once('error', reject); });
    const connected = new Promise(resolve => ws.on('message', raw => { const event = JSON.parse(raw); events.push(event); if (event.type === 'connected') resolve(); }));
    ws.send(JSON.stringify({ type: 'auth', token: service.token, clientId: 'test', surface: 'chats' }));
    await connected;

    assert.equal((await draft({ text: 'hi' }, {})).status, 401);
    assert.equal((await draft({ text: 'hi' })).status, 409);                       // no chat is selected yet
    ws.send(JSON.stringify({ type: 'selected', id: session.id }));
    await new Promise(resolve => setTimeout(resolve, 100));
    const ok = await draft({ text: 'Fix the hover gate' });
    assert.equal(ok.status, 200);
    assert.deepEqual(await ok.json(), { sessionId: session.id, name: 'Draft fixture' });
    await new Promise(resolve => setTimeout(resolve, 100));
    const drafts = events.filter(event => event.type === 'chat-draft');
    assert.deepEqual(drafts, [{ type: 'chat-draft', sessionId: session.id, text: 'Fix the hover gate' }]);
    const draftAt = events.indexOf(drafts[0]);
    assert.ok(events.slice(draftAt).some(event => event.type === 'navigate' && event.window === 'chats' && event.sessionId === session.id));
    assert.deepEqual(written, []);                                                   // a draft, never typed into the agent

    assert.equal((await draft({ text: 5 })).status, 400);
    assert.equal((await draft({ text: '   ' })).status, 400);
    assert.equal((await draft({ text: 'x'.repeat(9 * 1024) })).status, 400);
    assert.equal((await draft({ text: 'hi', sessionId: 'nope' })).status, 404);
  } finally {
    ws.close();
    await service.close();
  }
});
