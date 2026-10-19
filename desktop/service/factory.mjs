// /factory/* routes for the Asset Studio. The Python CLI is the only factory.db
// writer: this module reads the DB read-only and runs the CLI for every change.
import path from 'node:path';
import { access } from 'node:fs/promises';
import { DatabaseSync } from 'node:sqlite';
import { json, publicError, realFile } from './util.mjs';
import { serveFile } from './files.mjs';

const PACK_ID = /^[a-z][a-z0-9_]*$/;
const fail = (status, message, extra = {}) => Object.assign(new Error(message), { status, extra });

export function createFactory({ factoryDir, repo, runner = [process.execPath, [path.join(repo, 'scripts', 'run-python.mjs')]], db = path.join(factoryDir, 'factory.db') }) {
  // Opened per request and closed at once, so the CLI never waits on a handle we hold.
  function read(query) {
    let con;
    try {
      con = new DatabaseSync(db, { readOnly: true });
      return query(con);
    } catch (error) {
      if (error.errcode === 5 || /database is locked/i.test(error.message)) throw fail(503, 'Factory database is busy; retry on the next poll', { retry: true });
      if (/unable to open database/i.test(error.message)) return null;
      throw error;
    } finally { con?.close(); }
  }

  function packs() {
    return read(con => {
      const counts = {};
      for (const row of con.prepare('SELECT pack_id, status, COUNT(*) AS n FROM assets GROUP BY pack_id, status').all())
        (counts[row.pack_id] ||= {})[row.status] = row.n;
      const blockers = Object.fromEntries(con.prepare('SELECT a.pack_id, COUNT(*) AS n FROM v_license_blockers b JOIN assets a USING (asset_id) GROUP BY a.pack_id').all().map(row => [row.pack_id, row.n]));
      const release = con.prepare('SELECT * FROM releases WHERE pack_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1');
      return con.prepare('SELECT * FROM packs ORDER BY pack_id').all().map(pack => ({
        ...pack, counts: counts[pack.pack_id] || {}, blockers: blockers[pack.pack_id] || 0, last_release: release.get(pack.pack_id) || null,
      }));
    }) || [];
  }

  function pack(id) {
    const value = read(con => {
      const pack = con.prepare('SELECT * FROM packs WHERE pack_id = ?').get(id);
      if (!pack) return null;
      // Only the latest attempt under the current recipe counts, like the CLI report.
      const gates = con.prepare('SELECT gate, passed, measured, expected, created_at FROM gate_results WHERE asset_id = ? AND attempt = ? AND recipe = ?');
      const assets = con.prepare('SELECT * FROM assets WHERE pack_id = ? ORDER BY name').all(id)
        .map(asset => ({ ...asset, gates: gates.all(asset.asset_id, asset.attempts, pack.spec_hash) }));
      const provenance = con.prepare('SELECT p.* FROM provenance p JOIN assets a ON a.asset_id = p.asset_id AND a.run_id = p.run_id WHERE a.pack_id = ?').all(id);
      const releases = con.prepare('SELECT * FROM releases WHERE pack_id = ? ORDER BY created_at DESC, rowid DESC').all(id);
      return { ...pack, assets, provenance, releases };
    });
    if (!value) throw fail(404, 'Pack not found');
    return value;
  }

  async function file(request, response, rel) {
    if (!rel || path.isAbsolute(rel) || /^[a-z]:/i.test(rel)) throw fail(403, 'Only factory/build and factory/dist files are served');
    const [top, ...rest] = path.normalize(rel).split(/[\\/]/);
    if (!['build', 'dist'].includes(top) || !rest.length) throw fail(403, 'Only factory/build and factory/dist files are served');
    let found;
    try { found = await realFile(path.join(factoryDir, top), rest.join(path.sep)); }
    catch (error) { throw error.status ? error : fail(404, 'File not found'); }
    if (!found.info.isFile()) throw fail(404, 'File not found');
    await serveFile(request, response, found.file, found.info);
  }

  async function handle(request, response, url) {
    if (!url.pathname.startsWith('/factory/')) return false;
    try {
      const method = request.method;
      const detail = /^\/factory\/packs\/([^/]+)$/.exec(url.pathname);
      if (method === 'GET' && url.pathname === '/factory/packs') return json(response, 200, { packs: packs() }), true;
      if (method === 'GET' && detail) {
        if (!PACK_ID.test(detail[1])) throw fail(400, 'Invalid pack id');
        return json(response, 200, pack(detail[1])), true;
      }
      if (['GET', 'HEAD'].includes(method) && url.pathname === '/factory/file') return await file(request, response, url.searchParams.get('path')), true;
      throw fail(404, 'Endpoint not found');
    } catch (error) {
      if (!response.headersSent) json(response, error.status || 400, { error: publicError(error), ...error.extra });
    }
    return true;
  }

  return { handle, close() {} };
}
