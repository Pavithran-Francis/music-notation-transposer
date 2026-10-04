import { useEffect, useRef, useState } from 'react'
import { api, type Job } from './api'

/** Poll a background job until it finishes. */
export function useJob(jobId: string | null, onDone: (job: Job) => void) {
  const [job, setJob] = useState<Job | null>(null)
  const done = useRef(onDone)

  useEffect(() => {
    done.current = onDone
  }, [onDone])

  useEffect(() => {
    if (!jobId) return
    let cancelled = false
    let timer: number | undefined
    const tick = async () => {
      try {
        const j = await api.job(jobId)
        if (cancelled) return
        setJob(j)
        if (j.status === 'succeeded' || j.status === 'failed') {
          done.current(j)
          return
        }
      } catch {
        /* transient network error: keep polling */
      }
      timer = window.setTimeout(tick, 600)
    }
    tick()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [jobId])

  return jobId ? job : null
}
