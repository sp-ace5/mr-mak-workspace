import { useEffect, useState } from 'react'
import { FactoryError } from './api'

const POLL_MS = 5000

// Fetches now, every POLL_MS and whenever `refresh` changes. A busy DB (503)
// keeps the last data: the next poll retries.
export function usePoll<T>(load: () => Promise<T>, key: string, refresh = 0) {
  const [state, setState] = useState<{ key: string; data: T | null; error: string | null }>({ key, data: null, error: null })
  useEffect(() => {
    let alive = true
    const tick = () => load().then(
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
