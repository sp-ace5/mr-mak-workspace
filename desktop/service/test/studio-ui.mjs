// Asset Studio against a fixture factory/. The CLI is a node stub: no Python,
// butler, approve or publish ever runs.
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile } from 'node:fs/promises';
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

  assert.deepEqual(errors, []);
  console.log('Studio UI passed: pack list, pack page.');
} finally {
  await browser?.close();
  await service.close();
}
