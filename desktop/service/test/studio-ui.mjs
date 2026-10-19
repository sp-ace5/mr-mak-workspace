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

  const calls = await stubCalls();
  assert.deepEqual(calls[0], ['build', '--pack', 'spec/packs/ui_sfx_v1.yaml', '--json']);
  assert.ok(calls.every(call => call[0] !== 'publish'));

  assert.deepEqual(errors, []);
  console.log('Studio UI passed: pack list, pack page, job log, approve confirm, failures, missing tool.');
} finally {
  await browser?.close();
  await service.close();
}
