// Asset Studio against a fixture factory/. The CLI is a node stub: no Python,
// butler, approve or publish ever runs.
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createService } from '../server.mjs';
import { launchBrowser } from './browser.mjs';
import { stub, writeFactoryFixture } from './fixtures/factory-fixture.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
await mkdir(path.join(root, '.cache'), { recursive: true });
const repo = await mkdtemp(path.join(root, '.cache/studio-ui-'));
await mkdir(path.join(repo, 'workspace'), { recursive: true });
await writeFile(path.join(repo, 'workspace/workspace.json'), JSON.stringify({ entities: [] }));
const { env } = await writeFactoryFixture(repo);
Object.assign(process.env, env);
const service = await createService({ repo, uiDir: path.join(root, 'dist'), mcpOptions: { home: path.join(repo, 'fake-home'), env: {} }, factoryOptions: { runner: [process.execPath, [stub]] } });
let browser;
try {
  browser = await launchBrowser();
  const page = await (await browser.newContext({ viewport: { width: 1200, height: 800 } })).newPage();
  page.setDefaultTimeout(10000);
  const errors = []; page.on('pageerror', error => errors.push(error.message));

  await page.goto(service.urls.workspace + '#/@studio');
  await page.getByRole('link', { name: 'Asset Studio', includeHidden: true }).waitFor({ state: 'attached' });
  const row = page.locator('.studio-packs li', { hasText: 'ui_sfx_v1' });
  await row.waitFor();
  for (const text of ['approved 1', 'failed 1', 'shipped']) assert.ok((await row.textContent()).includes(text), text);

  // Playground: syncs, checks and opens via the (stubbed) CLI.
  await page.getByRole('button', { name: 'Open in playground' }).click();
  await page.getByRole('log', { name: 'playground log' }).getByText('done (exit 0)').waitFor();
  await page.getByRole('log', { name: 'playground log' }).getByText('opened playground').waitFor();
  assert.deepEqual(JSON.parse((await readFile(env.STUB_LOG, 'utf8')).trim().split('\n').at(-1)), ['playground', '--json', '--open']);

  // Pack page: gate table, audio from the content server, rendered VERIFY.md.
  await row.getByRole('link', { name: 'ui_sfx_v1' }).click();
  await page.getByRole('heading', { name: 'ui_sfx_v1', exact: true }).waitFor();
  assert.ok(page.url().endsWith('#/@studio/ui_sfx_v1'));
  const assets = page.getByRole('table', { name: 'Assets' });
  const click = assets.getByRole('row').filter({ hasText: 'click' });
  const hover = assets.getByRole('row').filter({ hasText: 'hover' });
  assert.ok((await click.textContent()).includes('approved'));
  for (const text of ['failed', 'peak', '0', '<=-1', 'not built']) assert.ok((await hover.textContent()).includes(text), text);
  await page.locator('audio').waitFor({ state: 'attached' });
  assert.equal(await page.locator('audio').count(), 1);
  assert.match(await page.locator('audio').getAttribute('src'), /\/view\//);
  await page.getByRole('heading', { name: 'VERIFY ui_sfx_v1' }).waitFor();

  // Ask agent: the failing asset's gates go into the selected chat as a draft, never sent.
  assert.equal(await click.getByRole('button', { name: 'Ask agent' }).count(), 0);   // only failing assets
  const written = [];
  const chat = service.sessions.make({ id: 'ask-chat', name: 'Factory chat', agent: 'codex', cwd: repo, status: 'running', open: true, cols: 80, rows: 30 });
  service.sessions.items.set(chat.id, chat); await service.sessions.hydrate(chat);
  chat.process = { write: data => written.push(data), resize() {}, kill() {} };
  const chats = await page.context().newPage();
  chats.setDefaultTimeout(10000);
  chats.on('pageerror', error => errors.push(`chats: ${error.message}`));
  await chats.goto(service.urls.chats);
  await chats.getByRole('tab', { name: /Factory chat/ }).click();               // selects it in the service
  await page.waitForTimeout(300);
  await hover.getByRole('button', { name: 'Ask agent' }).click();
  await page.getByRole('status').filter({ hasText: 'Draft added to Factory chat' }).waitFor();
  // Terminal view: no Conversation is open, so the draft waits in storage for the chat.
  await chats.waitForFunction(() => (localStorage.getItem('mrmak.chatDraft.ask-chat') || '').includes('ui_sfx_v1/hover'));
  // ...and the chat switched to its Conversation view by itself, where the composer is.
  await chats.locator('[aria-label="Chat view"] button[aria-pressed="true"]', { hasText: 'Conversation' }).waitFor();
  const composer = chats.locator('textarea[aria-label="Message Codex"]');
  for (const text of ['ui_sfx_v1/hover', 'peak: measured 0, expected <=-1', 'factory/spec/packs/ui_sfx_v1.yaml', 'Do not run approve or publish'])
    assert.ok((await composer.inputValue()).includes(text), text);
  // Conversation open: a second ask is appended to its draft, after a blank line.
  await hover.getByRole('button', { name: 'Ask agent' }).click();
  await chats.waitForFunction(() => document.querySelector('textarea[aria-label="Message Codex"]').value.split('ui_sfx_v1/hover').length === 3);
  assert.match(await composer.inputValue(), /Do not run approve or publish\. See the asset-factory skill\.\n\nAsset factory:/);
  assert.deepEqual(written.filter(data => String(data).includes('ui_sfx_v1')), []);  // nothing was typed into the agent
  await chats.close();

  // Actions: a job streams into the log; failures and missing tools are visible.
  assert.equal(await click.getByRole('checkbox').isDisabled(), true);
  assert.equal(await page.getByRole('button', { name: 'Approve selected' }).isDisabled(), true);
  const log = page.getByRole('log');
  await page.getByRole('button', { name: 'Build' }).click();
  await log.getByText('done (exit 0)').waitFor();
  for (const text of ['not json', 'warn']) await log.getByText(text, { exact: true }).first().waitFor();
  assert.equal(await page.getByRole('button', { name: 'Build' }).isDisabled(), false);

  // Approving is a user decision: a dismissed confirm runs nothing.
  await page.getByRole('checkbox', { name: 'Select tap' }).check();
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: 'Approve selected' }).click();
  await page.waitForTimeout(500);
  const stubCalls = async () => (await readFile(env.STUB_LOG, 'utf8')).split('\n').filter(Boolean).map(line => JSON.parse(line));
  assert.ok((await stubCalls()).every(call => call[0] !== 'approve'));
  page.once('dialog', dialog => { assert.equal(dialog.message(), 'Approve 1 asset in ui_sfx_v1?'); void dialog.accept(); });
  await page.getByRole('button', { name: 'Approve selected' }).click();
  await page.getByRole('log', { name: 'approve log' }).getByText('done (exit 0)').waitFor();
  assert.deepEqual((await stubCalls()).at(-1), ['approve', '--pack', 'spec/packs/ui_sfx_v1.yaml', '--json', '--only', 'tap']);

  process.env.STUB_MODE = 'argparse';
  await page.getByRole('button', { name: 'Package' }).click();
  await log.locator('.job-failed', { hasText: 'failed (exit 2)' }).waitFor();
  await log.getByText(/^usage:/).waitFor();

  process.env.STUB_MODE = 'ok';
  const missing = path.join(repo, 'no-godot.exe');
  process.env.STUB_CONFIG = JSON.stringify({ ...JSON.parse(env.STUB_CONFIG), tools: { godot: missing } });
  await page.getByRole('button', { name: 'Build' }).click();
  const card = page.getByRole('alert').filter({ hasText: 'godot' });
  await card.waitFor();
  assert.ok((await card.textContent()).includes(missing));

  // Publish: dry-run preview, exact typed confirm, then the real (stubbed) push.
  process.env.STUB_CONFIG = env.STUB_CONFIG;
  await page.getByRole('table', { name: 'Releases' }).getByText('me/ui_sfx_v1').waitFor();
  await page.getByRole('button', { name: 'Publish…' }).click();
  const dialog = page.getByRole('dialog', { name: 'Publish ui_sfx_v1' });
  await dialog.getByText('me/ui_sfx_v1:html5').waitFor();
  for (const text of ['godot-addon', 'me/ui_sfx_v1:godot-addon', 'a'.repeat(12)]) assert.ok((await dialog.textContent()).includes(text), text);
  const publish = dialog.getByRole('button', { name: 'Publish', exact: true });
  const confirm = dialog.getByRole('textbox', { name: /Type me\/ui_sfx_v1/ });
  assert.equal(await publish.isDisabled(), true);
  await confirm.fill('me/ui_sfx_v1 ');
  assert.equal(await publish.isDisabled(), true);
  await confirm.fill('me/ui_sfx_v1');
  await publish.click();
  await dialog.waitFor({ state: 'hidden' });
  await page.getByRole('log', { name: 'publish log' }).getByText('done (exit 0)').waitFor();
  await page.getByRole('log', { name: 'publish log' }).getByText('pushed me/ui_sfx_v1:html5').waitFor();
  const publishes = (await stubCalls()).filter(call => call[0] === 'publish');
  assert.deepEqual(publishes.map(call => call.includes('--dry-run')), [true, false]);

  process.env.STUB_MODE = 'refused';
  await page.getByRole('button', { name: 'Publish…' }).click();
  await dialog.getByText('not approved: hover').waitFor();
  assert.equal(await dialog.getByRole('textbox').count(), 0);
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await dialog.waitFor({ state: 'hidden' });

  process.env.STUB_MODE = 'nologin';
  await page.getByRole('button', { name: 'Publish…' }).click();
  await confirm.fill('me/ui_sfx_v1');
  await publish.click();
  await page.getByRole('alert').filter({ hasText: 'butler login' }).waitFor();
  process.env.STUB_MODE = 'ok';

  const calls = await stubCalls();
  assert.deepEqual(calls.find(call => call[0] === 'build'), ['build', '--pack', 'spec/packs/ui_sfx_v1.yaml', '--json']);
  assert.equal(calls.filter(call => call[0] === 'publish' && !call.includes('--dry-run')).length, 2);   // both stubbed, both typed-confirmed

  assert.deepEqual(errors, []);
  console.log('Studio UI passed: pack list, playground, pack page, ask agent, job log, approve confirm, failures, missing tool, publish dialog, refusal, butler login.');
} finally {
  await browser?.close();
  await service.close();
}
