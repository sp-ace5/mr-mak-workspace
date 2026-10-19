// One job per pack, kept outside React so a running job's log survives
// navigating away from its pack page and back.
import { useSyncExternalStore } from 'react'
import { FactoryError, runJob, type JobCommand, type JobEvent } from './api'

export interface Job { cmd: JobCommand; events: JobEvent[]; running: boolean; result: JobEvent | null; error: FactoryError | Error | null; finished: number }
const MAX_EVENTS = 500
const jobs = new Map<string, Job>()
const listeners = new Set<() => void>()
let finishedCount = 0

function set(pack: string, change: Partial<Job>) {
  jobs.set(pack, { ...jobs.get(pack)!, ...change })
  listeners.forEach(listener => listener())
}

export function startJob(pack: string, cmd: JobCommand, body: object = {}): Promise<Job> {
  const events: JobEvent[] = []
  set(pack, { cmd, events, running: true, result: null, error: null, finished: jobs.get(pack)?.finished ?? 0 })
  const onEvent = (event: JobEvent) => {
    events.push(event)
    if (events.length > MAX_EVENTS) events.splice(0, events.length - MAX_EVENTS)
    set(pack, { events: [...events] })
  }
  return runJob(pack, cmd, body, onEvent).then(
    result => { set(pack, { running: false, result, finished: ++finishedCount }); return jobs.get(pack)! },
    error => { set(pack, { running: false, error, finished: ++finishedCount }); return jobs.get(pack)! },
  )
}

const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }
export const useJob = (pack: string) => useSyncExternalStore(subscribe, () => jobs.get(pack) ?? null)
