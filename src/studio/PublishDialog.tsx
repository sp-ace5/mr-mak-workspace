import { useEffect, useRef, useState } from 'react'
import { startJob, type DryRun } from './jobs'

export default function PublishDialog({ id, preview, onClose }: { id: string; preview: Promise<DryRun>; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  const [result, setResult] = useState<DryRun | null>(null)
  const [typed, setTyped] = useState('')
  useEffect(() => {
    const dialog = ref.current!
    if (!dialog.open) dialog.showModal()
    let alive = true
    void preview.then(value => { if (alive) setResult(value) })
    return () => { alive = false }
  }, [preview])
  const expected = String(result?.pushes[0]?.target ?? '').split(':')[0]
  const ready = !!result && !result.refusal && !result.error && result.pushes.length > 0
  // expect: exactly what this preview listed; the CLI refuses if the files changed since.
  const publish = () => {
    void startJob(id, 'publish', { confirm: typed, expect: result!.pushes.map(push => `${String(push.channel)}:${String(push.sha256)}`) })
    ref.current?.close()
  }
  return <dialog ref={ref} className="studio-dialog" aria-label={`Publish ${id}`} onClose={onClose}>
    <h2>Publish {id}</h2>
    {!result && <p className="studio-muted">Checking what would be pushed…</p>}
    {result?.refusal && <p className="studio-error" role="alert">Publish refused: {result.refusal}</p>}
    {result?.error && <p className="studio-error" role="alert">{result.error}</p>}
    {result && !result.refusal && !result.error && !result.pushes.length && <p className="studio-error" role="alert">The dry run found nothing to push.</p>}
    {ready && <>
      <table className="studio-assets" aria-label="Pushes">
        <thead><tr><th>Channel</th><th>Target</th><th>SHA-256</th></tr></thead>
        <tbody>{result.pushes.map(push => <tr key={String(push.channel)}>
          <td>{String(push.channel)}</td><td>{String(push.target)}</td>
          <td><code title={String(push.sha256)}>{String(push.sha256).slice(0, 12)}</code></td>
        </tr>)}</tbody>
      </table>
      <p>This uploads to itch.io. Type <code>{expected}</code> to confirm.</p>
      <input autoFocus aria-label={`Type ${expected} to confirm`} value={typed} onChange={event => setTyped(event.target.value)} autoComplete="off" spellCheck={false} />
    </>}
    <div className="studio-toolbar">
      <button type="button" onClick={() => ref.current?.close()}>Cancel</button>
      {ready && <button type="button" className="danger" disabled={typed !== expected} onClick={publish}>Publish</button>}
    </div>
  </dialog>
}
