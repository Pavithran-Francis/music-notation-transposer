import { useCallback, useEffect, useState } from 'react'
import { AdvancedSettings } from '../components/AdvancedSettings'
import { AnalysisPanel } from '../components/AnalysisPanel'
import { InstrumentPicker } from '../components/InstrumentPicker'
import { JobProgress } from '../components/JobProgress'
import { PageStrip } from '../components/PageStrip'
import { ExportPanel, RangePanel, TranspositionSummary, ValidationPanel } from '../components/ResultPanels'
import { UploadArea } from '../components/UploadArea'
import { NoteEditor } from '../editors/NoteEditor'
import { ReviewPanel } from '../editors/ReviewPanel'
import { api, type Health, type Instrument, type InstrumentSpec, type Project, type Result, type Settings } from '../services/api'
import { useJob } from '../services/hooks'
import { ScoreViewer } from '../viewers/ScoreViewer'

interface Props {
  project: Project
  instruments: Instrument[]
  clefs: { id: string; label: string }[]
  health: Health | null
  onChanged: () => Promise<void> | void
}

export function Workspace({ project, instruments, clefs, health, onChanged }: Props) {
  const [jobId, setJobId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [reviewOpen, setReviewOpen] = useState(false)
  const [editNote, setEditNote] = useState<string | null>(null)
  const [rangeSel, setRangeSel] = useState<string[]>([])
  const [thumbBust, setThumbBust] = useState(0)
  const [busy, setBusy] = useState(false)
  const [source, setSource] = useState<InstrumentSpec | null>(project.source_instrument)
  const [target, setTarget] = useState<InstrumentSpec | null>(project.target_instrument)
  const [settings, setSettings] = useState<Settings>(project.settings ?? {})
  const [localResult, setLocalResult] = useState<Result | null>(null)

  // Sync local state when switching projects or after the server changed things.
  useEffect(() => {
    setSource(project.source_instrument)
    setTarget(project.target_instrument)
    setSettings(project.settings ?? {})
    setLocalResult(null)
    // resume watching an unfinished job (e.g. after reload)
    if (project.job && (project.job.status === 'queued' || project.job.status === 'running')) setJobId(project.job.id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id, project.updated_at])

  useEffect(() => { setReviewOpen(false); setEditNote(null); setRangeSel([]); setError(null) }, [project.id])

  const job = useJob(jobId, useCallback(async (j) => {
    await onChanged()
    if (j.status === 'succeeded') setJobId(null)
  }, [onChanged]))
  const running = !!job && (job.status === 'queued' || job.status === 'running')

  const guard = async (fn: () => Promise<unknown>) => {
    setError(null)
    setBusy(true)
    try { await fn() } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  const upload = (files: File[]) => guard(async () => {
    setUploading(true)
    try {
      await api.upload(project.id, files)
      setThumbBust((b) => b + 1)
      await onChanged()
      const { job_id } = await api.analyze(project.id) // analyze immediately after upload
      setJobId(job_id)
    } finally {
      setUploading(false)
    }
  })

  const persist = (patch: Parameters<typeof api.updateProject>[1]) => api.updateProject(project.id, patch).then(() => onChanged()).catch((e) => setError(e.message))

  const transpose = () => guard(async () => {
    if (!source || !target) throw new Error('Select both the original and the target instrument.')
    const { job_id } = await api.transpose(project.id, { source_instrument: source, target_instrument: target, settings })
    setJobId(job_id)
    setRangeSel([])
  })

  const applyCorrections = async (ops: Record<string, unknown>[]) => {
    for (const op of ops) await api.correction(project.id, op)
    await onChanged()
  }

  const analysis = project.analysis
  const result = localResult ?? project.result ?? null
  const hasResult = project.has_result && !!result
  const reviewItems = project.recognition?.review?.items ?? []
  const sourceHint = analysis?.parts[0]?.instrument_guess && project.source_instrument?.id === analysis.parts[0].instrument_guess
    ? 'Suggested from the score — please confirm.' : null
  const resultVersion = `${project.updated_at}-${JSON.stringify(result?.actions ?? [])}-${result?.octave_shifts ?? 0}-${result?.range.unacknowledged ?? 0}`

  return (
    <div className="workspace">
      {error && <div className="alert alert-error" role="alert">{error} <button className="link" onClick={() => setError(null)}>Dismiss</button></div>}
      {project.error && !running && project.status === 'failed' && (
        <div className="alert alert-error" role="alert">{project.error}</div>
      )}

      <div className="setup">
        <section className="card" aria-labelledby="upload-h">
          <h2 id="upload-h"><span className="step">1</span> Upload</h2>
          <UploadArea onFiles={upload} busy={uploading || running} uploading={uploading} maxMb={health?.limits.max_upload_mb ?? 50} currentFile={project.original_filename} />
          {health && !health.omr.available && (
            <p className="small alert alert-warn">The OMR engine (Audiveris) is not installed, so only MusicXML/MuseScore uploads can be processed. See README.</p>
          )}
          <PageStrip
            projectId={project.id} pageCount={project.page_count} rotations={project.page_rotations ?? []}
            bust={thumbBust} disabled={running || busy}
            onRotate={(page, deg) => guard(async () => {
              await api.rotatePage(project.id, page, deg)
              setThumbBust((b) => b + 1)
              await onChanged()
            })}
            onOpen={(page) => window.open(api.thumbnailUrl(project.id, page, thumbBust), '_blank')}
          />
          {project.page_count > 0 && analysis && (project.page_rotations ?? []).some(Boolean) && (
            <button className="btn btn-sm" disabled={running} onClick={() => guard(async () => setJobId((await api.analyze(project.id)).job_id))}>
              Re-run recognition with rotated pages
            </button>
          )}
        </section>

        <section className="card" aria-labelledby="inst-h">
          <h2 id="inst-h"><span className="step">2</span> Instruments</h2>
          <InstrumentPicker id="src" label="Original instrument" instruments={instruments} clefs={clefs} value={source} hint={sourceHint}
            disabled={running}
            onChange={(s) => { setSource(s); persist({ source_instrument: s }) }} />
          <InstrumentPicker id="tgt" label="Target instrument" instruments={instruments} clefs={clefs} value={target}
            disabled={running}
            onChange={(t) => { setTarget(t); persist({ target_instrument: t }) }} />
          <AdvancedSettings settings={settings} parts={analysis?.parts ?? []} disabled={running}
            onChange={(s) => { setSettings(s); persist({ settings: s }) }} />
          <div className="actions">
            {project.source_kind && !analysis && !running && (
              <button className="btn" onClick={() => guard(async () => setJobId((await api.analyze(project.id)).job_id))}>Analyze score</button>
            )}
            <button className="btn btn-primary btn-lg" disabled={!analysis || !source || !target || running || busy} onClick={transpose}>
              {hasResult ? 'Transpose again' : 'Generate transposed score'}
            </button>
          </div>
          {!project.source_kind && <p className="small muted">Upload a score to begin.</p>}
          {project.result_stale && hasResult && !running && <p className="small warn-text">Changes since the last transposition — transpose again to update the result.</p>}
        </section>
      </div>

      <JobProgress job={job} />

      {analysis && (
        <AnalysisPanel analysis={analysis} recognition={project.recognition} source={source} instruments={instruments} clefs={clefs}
          pageCount={project.page_count} busy={busy || running}
          onCorrect={(op) => guard(() => applyCorrections([op]))}
          onReview={() => setReviewOpen(true)} />
      )}

      {analysis && reviewOpen && (
        <ReviewPanel items={reviewItems} corrections={project.corrections?.length ?? 0} busy={busy}
          onSelectNote={setEditNote} onClose={() => setReviewOpen(false)}
          onUndo={() => guard(async () => { await api.undoCorrection(project.id); await onChanged() })} />
      )}

      {analysis && (
        <section className="previews" aria-label="Preview">
          <ScoreViewer
            projectId={project.id} which="original" title="Original score"
            version={`${project.updated_at}-${project.corrections?.length ?? 0}`}
            scanPages={project.page_count} thumbBust={thumbBust}
            selectedNoteId={editNote}
            onNoteClick={(id) => setEditNote(id)}
            legend={project.recognition?.review?.summary
              ? <>Click a note to correct it. <span className="swatch orange" /> uncertain <span className="swatch red" /> very uncertain <span className="swatch green" /> corrected</>
              : <>Click a note to correct it.</>}
          />
          {hasResult ? (
            <ScoreViewer
              projectId={project.id} which="result" title={`Transposed — ${result!.target.name}`}
              version={resultVersion}
              onNoteClick={(id) => { if (result!.range.issues.some((i) => i.note_id === id)) setRangeSel((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id]) }}
              legend={<><span className="swatch red" /> outside range <span className="swatch orange" /> kept out of range <span className="swatch blue" /> octave adjusted</>}
            />
          ) : (
            <div className="viewer placeholder">
              <p className="muted">{running ? 'Working…' : 'The transposed score will appear here.'}</p>
            </div>
          )}
        </section>
      )}

      {hasResult && result && (
        <div className="results">
          <TranspositionSummary result={result} />
          <RangePanel projectId={project.id} result={result} selected={rangeSel} onSelect={setRangeSel}
            onResult={async (r) => { setLocalResult(r); setRangeSel([]); await onChanged() }} />
          <ValidationPanel result={result} />
          <ExportPanel projectId={project.id} result={result} stale={project.result_stale} />
        </div>
      )}

      {editNote && (
        <NoteEditor projectId={project.id} noteId={editNote} onClose={() => setEditNote(null)} onApply={applyCorrections} />
      )}
    </div>
  )
}
