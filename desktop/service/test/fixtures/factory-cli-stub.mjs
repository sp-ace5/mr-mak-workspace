// Stands in for `node scripts/run-python.mjs ...` in factory tests: never runs
// Python, butler, approve or publish. Records its arguments in $STUB_LOG.
import { appendFileSync } from 'node:fs';

const args = process.argv.slice(2);
const mode = process.env.STUB_MODE || 'ok';
const out = value => process.stdout.write((typeof value === 'string' ? value : JSON.stringify(value)) + '\n');
if (mode === 'nopython') { process.stderr.write('Python 3 not found. Tried: py -3\n'); process.exit(1); }
if (args[0] === '-c') { out(process.env.STUB_CONFIG); process.exit(0); }
const [, cmd, ...rest] = args;   // args[0] is run.py
appendFileSync(process.env.STUB_LOG, JSON.stringify([cmd, ...rest]) + '\n');
if (mode === 'argparse') { process.stderr.write('usage: run.py [-h] {new,...}\n'); process.exit(2); }
if (mode === 'nodone') { out({ event: 'log', msg: 'hi' }); process.exit(0); }
if (mode === 'donefail') { out({ event: 'done', cmd, exit: 0 }); process.exit(3); }
if (mode === 'slow') await new Promise(resolve => setTimeout(resolve, 800));
out({ event: 'log', msg: 'hi' });
out('not json');
process.stderr.write('warn\n');
out({ event: 'done', cmd, exit: 0 });
