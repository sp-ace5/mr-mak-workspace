// Client for the service's /factory/* routes (desktop/service/factory.mjs).
// Every write goes through the Python CLI as a job; reads come from factory.db.
import { authHeader } from '../desktop/client'

export interface Release { channel: string; target: string; file_sha256: string; butler_build: string | null; created_at: string }
export interface PackSummary { pack_id: string; category: string; counts: Record<string, number>; blockers: number; last_release: Release | null }
export interface Gate { gate: string; passed: 0 | 1; measured: string | null; expected: string | null }
export interface Asset { asset_id: string; name: string; kind: string; status: string; attempts: number; output_path: string | null; gates: Gate[] }
export interface PackDetail extends PackSummary { spec_hash: string; assets: Asset[]; provenance: object[]; releases: Release[] }
export interface JobEvent { event: string; msg?: string; message?: string; exit?: number; synthetic?: boolean; [key: string]: unknown }
export type JobCommand = 'build' | 'approve' | 'package' | 'listing' | 'publish'

export class FactoryError extends Error {
  status: number
  body: Record<string, unknown>
  constructor(status: number, body: Record<string, unknown>) {
    super(typeof body.error === 'string' ? body.error : `Request failed (${status})`)
    this.status = status
    this.body = body
  }
}

async function fail(response: Response): Promise<never> {
  throw new FactoryError(response.status, await response.json().catch(() => ({})))
}

export async function factory<T>(path: string): Promise<T> {
  const response = await fetch(`/factory${path}`, { headers: authHeader() })
  if (!response.ok) await fail(response)
  return response.json() as Promise<T>
}

// Streams the job's SSE frames to onEvent; resolves with the final `done`
// (the service always sends one, synthesising it when the CLI did not).
export async function runJob(pack: string, cmd: JobCommand, body: object, onEvent: (event: JobEvent) => void): Promise<JobEvent> {
  const response = await fetch(`/factory/packs/${encodeURIComponent(pack)}/${cmd}`, {
    method: 'POST', headers: { ...authHeader(), 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  if (!response.ok || !response.body) await fail(response)
  const reader = response.body!.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  let done: JobEvent = { event: 'done', cmd, exit: 1, synthetic: true, msg: 'connection closed before the job finished' }
  try {
    for (;;) {
      // A dropped connection ends the stream like EOF: the log so far stays and the synthetic done shows.
      const { value, done: ended } = await reader.read().catch(() => ({ value: undefined, done: true }))
      if (value) buffer += value
      const frames = buffer.split('\n\n')
      buffer = ended ? '' : frames.pop()!
      for (const frame of frames) {
        if (!frame.startsWith('data: ')) continue
        let event: JobEvent
        try { event = JSON.parse(frame.slice(6)) as JobEvent } catch { event = { event: 'log', msg: frame.slice(6) } }
        if (event.event === 'done') done = event
        onEvent(event)
      }
      if (ended) return done
    }
  } finally { reader.cancel().catch(() => {}) }
}

// Absolute path of a file under factory/, in the separator style the repo path uses.
export function factoryPath(repo: string, rel: string): string {
  const sep = repo.includes('\\') ? '\\' : '/'
  return [repo.replace(/[\\/]+$/, ''), 'factory', ...rel.split('/')].join(sep)
}
