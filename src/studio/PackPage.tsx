import { useEffect, useRef, useState } from 'react'
import { api, setPreview, useDesktop } from '../desktop/client'
import type { Preview } from '../desktop/types'
import { MarkdownView } from '../components/MarkdownDocument'
import { factory, FactoryError, factoryPath, type Asset, type JobCommand, type JobEvent, type PackDetail } from './api'
import { startJob, useJob, type Job } from './jobs'
import { loadPreview, usePoll, usePreview } from './poll'

const STATUSES = ['pending', 'failed', 'passed', 'approved', 'rejected']

export function Chips({ counts, shipped }: { counts: Record<string, number>; shipped?: boolean }) {
  return <span className="studio-chips">
    {STATUSES.filter(status => counts[status]).map(status => <span key={status} className={`studio-chip ${status}`}>{status} {counts[status]}</span>)}
    {shipped && <span className="studio-chip shipped">shipped</span>}
  </span>
}

function Toolbar({ id, pack, repo, job, selected, refresh }: { id: string; pack: PackDetail; repo: string; job: Job | null; selected: Set<string>; refresh: number }) {
  const [note, setNote] = useState('')
  const demo = usePreview(factoryPath(repo, `dist/${id}/web_demo/index.html`), refresh)
  const busy = !!job?.running
  const passed = pack.assets.filter(asset => asset.status === 'passed').map(asset => asset.name)
  const picked = [...selected].filter(name => passed.includes(name))
  const run = (cmd: JobCommand, body: object = {}) => { setNote(''); return startJob(id, cmd, body) }
  const approve = (names: string[]) => { if (window.confirm(`Approve ${names.length} asset${names.length === 1 ? '' : 's'} in ${id}?`)) void run('approve', { names }) }
  const copyListing = async () => {
    const done = await run('listing')
    if (done.result?.exit !== 0) return
    const listing = await loadPreview(factoryPath(repo, `dist/${id}/listing.md`), true)
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
    {note && <span className="studio-muted" role="status">{note}</span>}
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
  return <p className="studio-error" role="alert">{error instanceof FactoryError && error.status === 409 ? 'A job is already running for this pack.' : error.message}</p>
}

// Last 500 events of this pack's latest job, newest at the bottom.
function JobLog({ job }: { job: Job | null }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight }, [job?.events, job?.result])
  if (!job) return null
  if (job.error) return <JobError error={job.error} />
  const events = job.result && !job.events.includes(job.result) ? [...job.events, job.result] : job.events
  return <div className="studio-log" role="log" aria-label={`${job.cmd} log`} ref={ref}>
    {events.map((event, index) => <div key={index} className={event.event === 'done' ? (event.exit === 0 ? 'job-done' : 'job-failed') : event.event === 'stderr' ? 'job-stderr' : undefined}>{line(event)}</div>)}
    {job.running && <div className="studio-muted">{job.cmd} running…</div>}
  </div>
}

interface Listing { entries: { name: string; path: string; directory: boolean }[] }
const list = (folder: string) => api<Listing>(`/files?path=${encodeURIComponent(folder)}`).then(value => value.entries, () => [])

// First, middle and last frame the preview rig rendered for a shader (first renderer folder).
function Frames({ folder }: { folder: string }) {
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
  }, [folder])
  return <span className="studio-frames">{frames.map(frame => <button key={frame.path} type="button" onClick={() => setPreview(frame)} title={frame.name}><img src={frame.url} alt={frame.name} /></button>)}</span>
}

function Media({ asset, repo, pack }: { asset: Asset; repo: string; pack: string }) {
  const audio = usePreview(asset.output_path && /\.wav$/i.test(asset.output_path) ? asset.output_path : null)
  if (!asset.output_path) return <span className="studio-muted">not built</span>
  if (audio?.url) return <audio controls preload="none" src={audio.url} />
  if (asset.kind === 'shader') return <Frames folder={factoryPath(repo, `build/${pack}/preview/${asset.name}`)} />
  return null
}

export default function PackPage({ id }: { id: string }) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const onSelect = (name: string, on: boolean) => setSelected(current => { const next = new Set(current); if (on) next.add(name); else next.delete(name); return next })
  const job = useJob(id)
  const refresh = job?.finished ?? 0
  const { repo } = useDesktop()
  const { data: pack, error } = usePoll(() => factory<PackDetail>(`/packs/${encodeURIComponent(id)}`), `pack:${id}`, refresh)
  const verify = usePreview(factoryPath(repo, `dist/${id}/VERIFY.md`), refresh)
  if (error) return <p className="studio-error" role="alert">{error}</p>
  if (!pack) return <p className="studio-muted">Loading {id}…</p>
  const counts: Record<string, number> = {}
  for (const asset of pack.assets) counts[asset.status] = (counts[asset.status] || 0) + 1
  return <>
    <Chips counts={counts} shipped={pack.releases.length > 0} />
    <Toolbar id={id} pack={pack} repo={repo} job={job} selected={selected} refresh={refresh} />
    <JobLog job={job} />
    <table className="studio-assets" aria-label="Assets">
      <thead><tr><th aria-label="Select" /><th>Asset</th><th>Kind</th><th>Status</th><th>Attempts</th><th>Failed gates</th><th>Preview</th></tr></thead>
      <tbody>{pack.assets.map(asset => <tr key={asset.asset_id}>
        <td><input type="checkbox" aria-label={`Select ${asset.name}`} disabled={asset.status !== 'passed'} checked={selected.has(asset.name)} onChange={event => onSelect(asset.name, event.target.checked)} /></td>
        <td>{asset.name}</td>
        <td>{asset.kind}</td>
        <td><span className={`studio-chip ${asset.status}`}>{asset.status}</span></td>
        <td>{asset.attempts}</td>
        <td>{asset.gates.filter(gate => !gate.passed).map(gate => <div key={gate.gate} className="studio-gate"><b>{gate.gate}</b>: {gate.measured ?? '—'} <span className="studio-muted">(expected {gate.expected ?? '—'})</span></div>)}</td>
        <td><Media asset={asset} repo={repo} pack={id} /></td>
      </tr>)}</tbody>
    </table>
    <section className="studio-verify">
      {verify?.kind === 'text' && verify.text ? <MarkdownView text={verify.text} baseUrl={verify.url} /> : <p className="studio-muted">Run Build to write VERIFY.md.</p>}
    </section>
  </>
}
