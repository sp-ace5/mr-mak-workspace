import { useEffect, useState } from 'react'
import { api } from '../desktop/client'
import type { Preview } from '../desktop/types'
import { FactoryError } from './api'

const POLL_MS = 5000

// Fetches now, every POLL_MS and whenever `refresh` changes. A busy DB (503)
// keeps the last data: the next poll retries.
export function usePoll<T>(load: () => Promise<T>, key: string, refresh = 0) {
  const [state, setState] = useState<{ key: string; data: T | null; error: string | null }>({ key, data: null, error: null })
  useEffect(() => {
    let alive = true
    const tick = () => document.hidden ? undefined : load().then(
      data => { if (alive) setState({ key, data, error: null }) },
      error => { if (alive && !(error instanceof FactoryError && error.status === 503)) setState(s => ({ key, data: s.key === key ? s.data : null, error: error.message })) },
    )
    tick()
    const timer = setInterval(tick, POLL_MS)
    return () => { alive = false; clearInterval(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` names what `load` fetches
  }, [key, refresh])
  return state.key === key ? state : { key, data: null, error: null }
}

// /api/preview returns token-free content-server URLs an <audio> or <img> can load.
export const loadPreview = (file: string) => api<Preview>(`/preview?path=${encodeURIComponent(file)}`).catch(() => null)

// Refetches whenever `version` changes (pack data or a finished job), so a build
// run from a terminal still updates VERIFY.md, audio and the web demo button.
export function usePreview(file: string | null, version = '') {
  const [state, setState] = useState<{ key: string; preview: Preview | null }>({ key: '', preview: null })
  const key = `${file}\n${version}`
  useEffect(() => {
    let alive = true
    if (file) void loadPreview(file).then(preview => { if (alive) setState({ key, preview }) })
    return () => { alive = false }
  }, [file, key])
  return state.key.split('\n')[0] === String(file) ? state.preview : null
}
