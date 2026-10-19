// A factory/ under `root` with a fixture DB, build/dist files and one pack spec,
// plus fake godot/butler files beside it and a secret.txt no route may serve.
// Returns the env the CLI stub (factory-cli-stub.mjs) reads.
import path from 'node:path';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { DatabaseSync } from 'node:sqlite';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');
export const stub = path.join(path.dirname(fileURLToPath(import.meta.url)), 'factory-cli-stub.mjs');

export async function writeFactoryFixture(root) {
  const factoryDir = path.join(root, 'factory');
  for (const dir of ['dist/ui_sfx_v1', 'build/ui_sfx_v1', 'spec/packs']) await mkdir(path.join(factoryDir, dir), { recursive: true });
  await writeFile(path.join(root, 'secret.txt'), 'secret');
  await writeFile(path.join(factoryDir, 'dist/ui_sfx_v1/listing.md'), '# UI SFX');
  await writeFile(path.join(factoryDir, 'dist/ui_sfx_v1/VERIFY.md'), '# VERIFY ui_sfx_v1\n');
  const wav = path.join(factoryDir, 'build/ui_sfx_v1/a.wav');
  await writeFile(wav, 'RIFF');
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
      ('ui_sfx_v1/hover', 'ui_sfx_v1', 'ui_sfx', 'hover', 'failed', 2, 'r2'),
      ('ui_sfx_v1/tap', 'ui_sfx_v1', 'ui_sfx', 'tap', 'passed', 1, 'r3');
    INSERT INTO gate_results (asset_id, attempt, recipe, gate, passed, measured, expected) VALUES
      ('ui_sfx_v1/hover', 1, 'h1', 'peak', 1, '-3', '<=-1'),
      ('ui_sfx_v1/hover', 2, 'h1', 'peak', 0, '0', '<=-1'),
      ('ui_sfx_v1/hover', 2, 'old', 'peak', 1, '-3', '<=-1');
    INSERT INTO provenance (asset_id, run_id, step, tool, license_id, ai_generated) VALUES
      ('ui_sfx_v1/click', 'r1', 'synth', 'factory.sfx_ui', 'own-work', 0),
      ('ui_sfx_v1/click', 'old', 'synth', 'factory.sfx_ui', 'own-work', 0);
    INSERT INTO releases (pack_id, channel, target, file_sha256, spec_hash) VALUES ('ui_sfx_v1', 'godot-addon', 'me/ui_sfx_v1', 'abc', 'h1');
  `);
  db.prepare('UPDATE assets SET output_path = ? WHERE asset_id = ?').run(wav, 'ui_sfx_v1/click');
  db.close();
  const config = { tools: { godot: path.join(root, 'godot.exe'), butler: path.join(root, 'butler.exe') }, itch: { user: 'me' } };
  return { factoryDir, env: { STUB_LOG: path.join(root, 'stub.log'), STUB_MODE: 'ok', STUB_CONFIG: JSON.stringify(config) } };
}
