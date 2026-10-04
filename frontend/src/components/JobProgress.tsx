import type { Job } from '../services/api'

export function JobProgress({ job }: { job: Job | null }) {
  if (!job || job.status === 'succeeded') return null
  const pct = Math.round((job.progress || 0) * 100)
  if (job.status === 'failed') {
    return <div className="alert alert-error" role="alert"><strong>Processing failed.</strong> {job.message}</div>
  }
  return (
    <div className="job" role="status" aria-live="polite">
      <div className="job-msg">{job.status === 'queued' ? 'Queued…' : job.message}</div>
      <div className="progress" aria-hidden="true"><div className="progress-bar" style={{ width: `${Math.max(pct, 4)}%` }} /></div>
    </div>
  )
}
