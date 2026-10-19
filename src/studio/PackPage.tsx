import { useEffect, useRef, useState } from 'react'
import { api, setPreview, useDesktop } from '../desktop/client'
import type { Preview } from '../desktop/types'
import { MarkdownView } from '../components/MarkdownDocument'
import { factory, FactoryError, factoryPath, type Asset, type JobCommand, type JobEvent, type PackDetail, type Release } from './api'
import PublishDialog from './PublishDialog'
import { dryRun, startJob, useJob, type DryRun, type Job } from './jobs'
import { loadPreview, usePoll, usePreview } from './poll'

const STATUSES = ['pending', 'failed', 'passed', 'approved', 'rejected']

export function Chips({ counts, shipped }: { counts: Record<string, number>; shipped?: boolean }) {
  return <span className="studio-chips">
    {STATUSES.filter(status => counts[status]).map(status => <span key={status} className={`studio-chip ${status}`}>{status} {counts[status]}</span>)}
    {shipped && <span className="studio-chip shipped">shipped</span>}
  </span>
}

function Toolbar({ id, pack, repo, job, selected, version }: { id: string; pack: PackDetail; repo: string; job: Job | null; selected: Set<string>; version: string }) {
  const [note, setNote] = useState('')
  const [publishing, setPublishing] = useState<Promise<DryRun> | null>(null)
  const demo = usePreview(factoryPath(repo, `dist/${id}/web_demo/index.html`), version)
  // A dry run holds the pack's server lock too, even after its dialog is cancelled.
  const [previewing, setPreviewing] = useState(false)
  const busy = !!job?.running || previewing
  const openPublish = () => {
    const preview = dryRun(id)
    setPreviewing(true)
    void preview.finally(() => setPreviewing(false))
    setPublishing(preview)
  }
  const passed = pack.assets.filter(asset => asset.status === 'passed').map(asset => asset.name)
  const picked = [...selected].filter(name => passed.includes(name))
  const run = (cmd: JobCommand, body: object = {}) => { setNote(''); return startJob(id, cmd, body) }
  const approve = (names: string[]) => { if (window.confirm(`Approve ${names.length} asset${names.length === 1 ? '' : 's'} in ${id}?`)) void run('approve', { names }) }
  const copyListing = async () => {
    const done = await run('listing')
    if (done.result?.exit !== 0) return
    const listing = await loadPreview(factoryPath(repo, `dist/${id}/listing.md`))
    if (!listing?.text) return setNote('listing.md was not written')
    await navigator.clipboard.writeText(listing.text).then(() => setNote('Listing copied'), () => setNote('Clipboard is not available'))
  }
  return <div className="studio-toolbar">
    <button type="button" disabled={busy} onClick={() => void run('build')}>Build</button>
    <button type="button" disabled={busy || !picked.length} onClick={() => approve(picked)}>Approve selected</button>
    <button type="button" disabled={busy || !passed.length} onClick={() => approve(passed)}>Approve all passed</button>
    <button type="button" disabled={busy} onClick={() => void run('package')}>Package</button>
    <button type="button" disabled={busy} onClick={() => void copyListing()}>Copy listing</button>
    <button type="button" disabled={!demo?.url} onClick={() => demo && setPreview(demo)}>Open web demo</button>
    <button type="button" disabled={busy || !!publishing} onClick={openPublish}>Publish…</button>
    {publishing && <PublishDialog id={id} preview={publishing} onClose={() => setPublishing(null)} />}
    <span className="studio-muted" role="status">{note}</span>
  </div>
}

const line = (event: JobEvent) => event.event === 'done'
  ? (event.exit === 0 ? 'done (exit 0)' : `failed (exit ${event.exit ?? '?'})${typeof event.msg === 'string' ? ' — ' + event.msg : ''}`)
  : typeof event.msg === 'string' ? event.msg : typeof event.message === 'string' ? event.message : JSON.stringify(event)

function JobError({ error }: { error: Error }) {
  if (error instanceof FactoryError && error.status === 424) {
    const tool = String(error.body.tool ?? '')
    return <div className="studio-setup" role="alert">
      <b>Setup needed: {tool}</b>
      <p>{tool === 'python' ? 'Install Python 3 so the factory CLI can run.' : `${tool} not found at "${String(error.body.path ?? '')}" — set it in factory/spec/global.local.yaml.`}</p>
    </div>
  }
  return <p className="studio-error" role="alert">{error.message}</p>
}

// Last 500 events of this pack's latest job, newest at the bottom.
export function JobLog({ job }: { job: Job | null }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight }, [job?.events, job?.result])
  if (!job) return null
  if (job.error) return <JobError error={job.error} />
  const events = job.result && !job.events.includes(job.result) ? [...job.events, job.result] : job.events
  // Butler without a stored login fails the push; it needs a terminal once (spec section 7).
  const login = job.cmd === 'publish' && events.some(event => event.event === 'error' && LOGIN.test(String(event.message ?? '')))
  return <>
    {login && <div className="studio-setup" role="alert"><b>Setup needed: butler login</b><p>Run <code>butler login</code> in a terminal once, then publish again.</p></div>}
    <div className="studio-log" role="log" aria-label={`${job.cmd} log`} ref={ref}>
      {events.map((event, index) => <div key={index} className={event.event === 'done' ? (event.exit === 0 ? 'job-done' : 'job-failed') : event.event === 'stderr' ? 'job-stderr' : undefined}>{line(event)}</div>)}
      {job.running && <div className="studio-muted">{job.cmd} running…</div>}
    </div>
  </>
}

// Tested against butler's own output only: msg carries the target, which may contain "login".
// What "Ask agent" drafts into the active chat (spec section 4): the failures, where the source is,
// and the rules from the asset-factory skill. The user reads it and presses Send.
function askText(pack: string, asset: Asset): string {
  const sources = [`factory/spec/packs/${pack}.yaml`, ...(asset.kind === 'shader' ? [`factory/shaders/${pack}/${asset.name}.gdshader`] : [])]
  return [
    `Asset factory: ${pack}/${asset.name} (${asset.kind}) failed its gates on attempt ${asset.attempts}:`,
    ...asset.gates.filter(gate => !gate.passed).map(gate => `- ${gate.gate}: measured ${gate.measured ?? '—'}, expected ${gate.expected ?? '—'}`),
    `Sources: ${sources.join(', ')}`,
    'Fix the source (generator, shader or spec), never files under factory/build/. Then rebuild with',
    `\`node scripts/run-python.mjs factory/pipeline/run.py build --pack spec/packs/${pack}.yaml --json\`.`,
    'Do not run approve or publish. See the asset-factory skill.',
  ].join('\n')
}

// Resolves with the note to show: where the draft went, or why it could not.
function askAgent(pack: string, asset: Asset): Promise<string> {
  return api<{ name: string }>('/chats/draft', { text: askText(pack, asset) }).then(
    ({ name }) => `Draft added to ${name}. Review it in Chats, then send.`,
    error => error instanceof Error ? error.message : String(error),
  )
}

const LOGIN =/\bbutler login\b|not logged in|credentials/i

function Releases({ releases }: { releases: Release[] }) {
  if (!releases.length) return null
  return <>
    <h3>Releases</h3>
    <table className="studio-assets" aria-label="Releases">
      <thead><tr><th>Channel</th><th>Target</th><th>SHA-256</th><th>When</th></tr></thead>
      <tbody>{releases.map((release, index) => <tr key={index}>
        <td>{release.channel}</td><td>{release.target}</td>
        <td><code title={release.file_sha256}>{release.file_sha256.slice(0, 12)}</code></td><td>{release.created_at}</td>
      </tr>)}</tbody>
    </table>
  </>
}

interface Listing { entries: { name: string; path: string; directory: boolean }[] }
const list = (folder: string) => api<Listing>(`/files?path=${encodeURIComponent(folder)}`).then(value => value.entries, () => [])

// First, middle and last frame the preview rig rendered for a shader (first renderer folder).
function Frames({ folder, version }: { folder: string; version: string }) {
  const [frames, setFrames] = useState<Preview[]>([])
  useEffect(() => {
    let alive = true
    void (async () => {
      const renderer = (await list(folder)).find(entry => entry.directory)
      if (!renderer) return
      const pngs = (await list(renderer.path)).filter(entry => /\.png$/i.test(entry.name)).sort((a, b) => a.name.localeCompare(b.name))
      const picks = [...new Set([pngs[0], pngs[Math.floor(pngs.length / 2)], pngs[pngs.length - 1]])].filter(Boolean)
      const loaded = (await Promise.all(picks.map(entry => loadPreview(entry!.path)))).filter((value): value is Preview => !!value?.url)
      if (alive) setFrames(loaded)
    })()
    return () => { alive = false }
  }, [folder, version])
  return <span className="studio-frames">{frames.map(frame => <button key={frame.path} type="button" onClick={() => setPreview(frame)} title={frame.name}><img src={frame.url} alt={frame.name} /></button>)}</span>
}

function Media({ asset, repo, pack, version }: { asset: Asset; repo: string; pack: string; version: string }) {
  const audio = usePreview(asset.output_path && /\.wav$/i.test(asset.output_path) ? asset.output_path : null, version)
  if (!asset.output_path) return <span className="studio-muted">not built</span>
  if (audio?.url) return <audio controls preload="none" src={audio.url} aria-label={`Play ${asset.name}`} />
  if (asset.kind === 'shader') return <Frames folder={factoryPath(repo, `build/${pack}/preview/${asset.name}`)} version={version} />
  return null
}

export default function PackPage({ id }: { id: string }) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [asked, setAsked] = useState('')
  const onSelect = (name: string, on: boolean) => setSelected(current => { const next = new Set(current); if (on) next.add(name); else next.delete(name); return next })
  const job = useJob(id)
  const refresh = job?.finished ?? 0
  const { repo } = useDesktop()
  const { data: pack, error } = usePoll(() => factory<PackDetail>(`/packs/${encodeURIComponent(id)}`), `pack:${id}`, refresh)
  // Changes when a build ran (here or from a terminal), so previews refetch.
  const version = pack ? `${refresh}:${pack.assets.map(asset => `${asset.status}${asset.attempts}`).join()}:${pack.releases.length}` : `${refresh}`
  const verify = usePreview(factoryPath(repo, `dist/${id}/VERIFY.md`), version)
  if (error) return <p className="studio-error" role="alert">{error}</p>
  if (!pack) return <p className="studio-muted">Loading {id}…</p>
  const counts: Record<string, number> = {}
  for (const asset of pack.assets) counts[asset.status] = (counts[asset.status] || 0) + 1
  return <>
    <Chips counts={counts} shipped={pack.releases.length > 0} />
    <Toolbar id={id} pack={pack} repo={repo} job={job} selected={selected} version={version} />
    <JobLog job={job} />
    <p className="studio-muted" role="status">{asked}</p>
    <table className="studio-assets" aria-label="Assets">
      <thead><tr><th aria-label="Select" /><th>Asset</th><th>Kind</th><th>Status</th><th>Attempts</th><th>Failed gates</th><th>Preview</th></tr></thead>
      <tbody>{pack.assets.map(asset => <tr key={asset.asset_id}>
        <td><input type="checkbox" aria-label={`Select ${asset.name}`} disabled={asset.status !== 'passed'} checked={selected.has(asset.name)} onChange={event => onSelect(asset.name, event.target.checked)} /></td>
        <td>{asset.name}</td>
        <td>{asset.kind}</td>
        <td><span className={`studio-chip ${asset.status}`}>{asset.status}</span></td>
        <td>{asset.attempts}</td>
        <td>
          {asset.gates.filter(gate => !gate.passed).map(gate => <div key={gate.gate} className="studio-gate"><b>{gate.gate}</b>: {gate.measured ?? '—'} <span className="studio-muted">(expected {gate.expected ?? '—'})</span></div>)}
          {asset.status === 'failed' && asset.gates.some(gate => !gate.passed) && <button type="button" className="studio-ask" onClick={() => void askAgent(id, asset).then(setAsked)}>Ask agent</button>}
        </td>
        <td><Media asset={asset} repo={repo} pack={id} version={version} /></td>
      </tr>)}</tbody>
    </table>
    <Releases releases={pack.releases} />
    <section className="studio-verify">
      {verify?.kind === 'text' && verify.text ? <MarkdownView text={verify.text} baseUrl={verify.url} /> : <p className="studio-muted">Run Build to write VERIFY.md.</p>}
    </section>
  </>
}
