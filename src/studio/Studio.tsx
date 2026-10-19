import { useEffect, useState } from 'react'
import { factory, type PackSummary } from './api'
import { usePoll } from './poll'
import PackPage, { Chips } from './PackPage'
import './studio.css'

// #/@studio → pack list, #/@studio/<pack_id> → pack page.
const packFromHash = () => decodeURIComponent(location.hash.replace(/^#\/?@studio\/?/, '').split('/')[0] || '') || null

function PackList() {
  const { data, error } = usePoll(() => factory<{ packs: PackSummary[] }>('/packs'), 'packs')
  if (error) return <p className="studio-error" role="alert">{error}</p>
  if (!data) return <p className="studio-muted">Loading packs…</p>
  if (!data.packs.length) return <p className="studio-muted">No packs yet — create one with <code>run.py new</code>.</p>
  return <ul className="studio-packs">
    {data.packs.map(pack => <li key={pack.pack_id}>
      <a href={`#/@studio/${encodeURIComponent(pack.pack_id)}`}>{pack.pack_id}</a>
      <span className="studio-muted">{pack.category}</span>
      <Chips counts={pack.counts} shipped={!!pack.last_release} />
      {pack.blockers > 0 && <span className="studio-chip blocker">{pack.blockers} blockers</span>}
      {pack.last_release && <span className="studio-muted">last release {pack.last_release.target} · {pack.last_release.created_at}</span>}
    </li>)}
  </ul>
}

export default function Studio() {
  const [pack, setPack] = useState(packFromHash)
  useEffect(() => {
    const onHash = () => setPack(packFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  return <section className="studio">
    <h1>Asset Studio</h1>
    {pack ? <><a href="#/@studio">← All packs</a><h2>{pack}</h2><PackPage key={pack} id={pack} /></> : <PackList />}
  </section>
}
