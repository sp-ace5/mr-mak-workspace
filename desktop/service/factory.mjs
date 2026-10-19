// /factory/* routes for the Asset Studio. The Python CLI is the only factory.db
// writer: this module reads the DB read-only and runs the CLI for every change.
import path from 'node:path';
import { access, mkdir } from 'node:fs/promises';
import { createWriteStream } from 'node:fs';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { DatabaseSync } from 'node:sqlite';
import { body, json, publicError, realFile } from './util.mjs';
import { serveFile } from './files.mjs';

const PACK_ID = /^[a-z][a-z0-9_]*$/;
// Tool each command needs before it can do anything useful.
// ponytail: mesh packs also need Blender on build; add when the first mesh pack ships.
const COMMANDS = { build: 'godot', approve: null, package: 'godot', listing: null, publish: 'butler' };
const ASSET_NAME = /^[\w.][\w.-]*$/;
const CONFIG = 'import json; from pipeline.run import global_spec; print(json.dumps(global_spec()))';
const fail = (status, message, extra = {}) => Object.assign(new Error(message), { status, extra });

export function createFactory({ factoryDir, repo, runner = [process.execPath, [path.join(repo, 'scripts', 'run-python.mjs')]], db = process.env.FACTORY_DB || path.join(factoryDir, 'factory.db') }) {
  const jobs = new Map();   // pack id -> { cmd, child }: one job per pack
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

  // Merged global.yaml + global.local.yaml, exactly as the CLI sees it.
  function config() {
    return new Promise((resolve, reject) => {
      const child = spawn(runner[0], [...runner[1], '-c', CONFIG], { cwd: factoryDir, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
      let stdout = '', stderr = '';
      child.stdout.on('data', chunk => { stdout += chunk; });
      child.stderr.on('data', chunk => { stderr += chunk; });
      child.on('error', error => reject(fail(424, `Python could not start: ${error.message}`, { tool: 'python', path: runner[0] })));
      child.on('close', code => {
        if (/Python 3 not found/.test(stderr)) return reject(fail(424, 'Python 3 not found', { tool: 'python', path: stderr.trim().split('Tried: ')[1] || '' }));
        try { if (code === 0) return resolve(JSON.parse(stdout)); } catch { /* reported below */ }
        reject(fail(500, `Factory config could not be read: ${stderr.trim().split('\n').slice(-3).join(' ') || `exit ${code}`}`));
      });
    });
  }

  async function needTool(name, configured) {
    if (!configured || !await access(configured).then(() => true, () => false))
      throw fail(424, `${name} not found at ${JSON.stringify(configured || '')}; set tools.${name} in factory/spec/global.local.yaml`, { tool: name, path: configured || '' });
  }

  // id null = the playground job, which spans every pack and has its own lock.
  async function startJob(request, response, id, cmd) {
    const playground = id === null && cmd === 'playground';
    const spec = `spec/packs/${id}.yaml`;
    if (!playground) {
      if (!PACK_ID.test(id)) throw fail(400, 'Invalid pack id');
      if (!(cmd in COMMANDS)) throw fail(404, 'Endpoint not found');
      if (!await access(path.join(factoryDir, spec)).then(() => true, () => false)) throw fail(404, 'Pack spec not found');
    }
    const key = playground ? '@playground' : id;
    // Body first: a client that never finishes sending it must not hold the pack's lock.
    const data = await body(request, 64 * 1024);
    if (jobs.has(key)) throw fail(409, playground ? 'The playground is already being prepared' : `A ${jobs.get(key).cmd} job is already running for ${id}`);
    // Reserve before the next await so two quick requests cannot both start.
    const job = { cmd, child: null };
    jobs.set(key, job);
    try {
      const args = [path.join(factoryDir, 'pipeline', 'run.py'), cmd, ...(playground ? [] : ['--pack', spec]), '--json'];
      if (data.open !== undefined && (!playground || typeof data.open !== 'boolean')) throw fail(400, 'open is a playground option: true or false');
      if (data.open === true) args.push('--open');
      if (cmd === 'approve') {
        if (!Array.isArray(data.names) || !data.names.length || !data.names.every(name => typeof name === 'string' && ASSET_NAME.test(name)))
          throw fail(400, 'approve needs {names: [asset names]}');
        args.push('--only', ...data.names);
      }
      if (data.dryRun !== undefined && (cmd !== 'publish' || typeof data.dryRun !== 'boolean')) throw fail(400, 'dryRun is a publish option: true or false');
      // A dry run pushes nothing, so it is the one publish that needs no typed confirmation.
      const dryRun = cmd === 'publish' && data.dryRun === true;
      if (dryRun) args.push('--dry-run');
      if (cmd === 'publish' && !dryRun && typeof data.confirm !== 'string') throw fail(400, 'publish needs {confirm: "<itch.user>/<pack>"}');
      const settings = await config();
      const tool = playground ? 'godot' : COMMANDS[cmd];
      if (tool) await needTool(tool, settings.tools?.[tool]);
      if (cmd === 'publish') {
        const user = settings.itch?.user;
        if (!user) throw fail(424, 'itch.user is not set; put it in factory/spec/global.local.yaml', { tool: 'itch.user', path: '' });
        if (!dryRun && data.confirm !== `${user}/${id}`) throw fail(400, `Confirmation does not match the publish target ${user}/${id}`, { target: `${user}/${id}` });
      }
      // Every job's events also go to factory/build/<pack>/jobs/<UTC stamp>-<cmd>.log (spec section 7); dry runs are named apart from real uploads.
      const stamp = new Date().toISOString().replace(/[-:]/g, '').replace('T', '-').slice(0, 15);
      const logDir = path.join(factoryDir, 'build', playground ? '_playground' : id, 'jobs');
      job.log = await mkdir(logDir, { recursive: true }).then(() => createWriteStream(path.join(logDir, `${stamp}-${cmd}${dryRun ? '-dry-run' : ''}.log`), { flags: 'a' }), error => error);
      job.child = spawn(runner[0], [...runner[1], ...args], { cwd: repo, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    } catch (error) { jobs.delete(key); job.log?.end?.(); throw error; }

    try {
      response.writeHead(200, { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no' });
      // The job outlives a closed client: stopping approve or publish halfway is worse than finishing.
      const send = event => {
        if (job.log && !(job.log instanceof Error)) job.log.write(JSON.stringify(event) + '\n');
        if (!response.writableEnded && !response.destroyed) response.write(`data: ${JSON.stringify(event)}\n\n`);
      };
      // A log that cannot be written is reported once; the job itself goes on.
      const logFailed = error => { job.log = null; send({ event: 'stderr', msg: `job log not written: ${error.message}` }); };
      if (job.log instanceof Error) logFailed(job.log); else job.log.on('error', logFailed);
      let done = null;
      const lines = (stream, wrap) => new Promise(resolve => createInterface({ input: stream }).on('line', wrap).on('close', resolve));
      const outputs = Promise.all([
        lines(job.child.stdout, line => {
          let event;
          try { event = JSON.parse(line); } catch { /* plain text */ }
          if (!event || typeof event !== 'object' || Array.isArray(event) || typeof event.event !== 'string') event = { event: 'log', msg: line };
          if (event.event === 'done') done = event;
          send(event);
        }),
        lines(job.child.stderr, line => send({ event: 'stderr', msg: line })),
      ]);
      const code = await new Promise(resolve => {
        job.child.on('error', error => { send({ event: 'error', message: error.message }); resolve(1); });
        job.child.on('close', resolve);
      });
      await outputs;
      // No done line (argparse error, Ctrl-C, crash) or an exit that contradicts it means failure.
      if (typeof done?.exit !== 'number' || done.exit !== code) send({ event: 'done', cmd, exit: code || 1, synthetic: true });
      await new Promise(resolve => job.log ? job.log.end(resolve) : resolve());   // log complete before the client sees the end
      response.end();
    } finally { jobs.delete(key); job.log?.end(); }
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
      const action = /^\/factory\/packs\/([^/]+)\/([^/]+)$/.exec(url.pathname);
      if (method === 'POST' && action) return await startJob(request, response, action[1], action[2]), true;
      if (method === 'POST' && url.pathname === '/factory/playground') return await startJob(request, response, null, 'playground'), true;
      throw fail(404, 'Endpoint not found');
    } catch (error) {
      if (!response.headersSent) json(response, error.status || 400, { error: publicError(error), ...error.extra });
    }
    return true;
  }

  // Jobs are not killed: killing the run-python.mjs wrapper would orphan Python mid-publish.
  // ponytail: output after the service exits is lost and a hung CLI holds its pack's 409
  // until restart; step 5 adds job log files, add a watchdog/cancel route if hangs show up.
  return { handle };
}
