import { useState } from 'react'
import type { Analysis, Instrument, InstrumentSpec, Recognition } from '../services/api'

const KEYS: [number, string][] = [
  [-7, 'Cb major / Ab minor'], [-6, 'Gb major / Eb minor'], [-5, 'Db major / Bb minor'], [-4, 'Ab major / F minor'],
  [-3, 'Eb major / C minor'], [-2, 'Bb major / G minor'], [-1, 'F major / D minor'], [0, 'C major / A minor'],
  [1, 'G major / E minor'], [2, 'D major / B minor'], [3, 'A major / F# minor'], [4, 'E major / C# minor'],
  [5, 'B major / G# minor'], [6, 'F# major / D# minor'], [7, 'C# major / A# minor'],
]

interface Props {
  analysis: Analysis
  recognition: Recognition | null | undefined
  source: InstrumentSpec | null
  instruments: Instrument[]
  clefs: { id: string; label: string }[]
  pageCount: number
  onCorrect: (op: Record<string, unknown>) => Promise<void>
  onReview: () => void
  busy: boolean
}

const pct = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v * 100)}%`)

export function AnalysisPanel({ analysis, recognition, source, instruments, clefs, pageCount, onCorrect, onReview, busy }: Props) {
  const [editing, setEditing] = useState(false)
  const [key, setKey] = useState(analysis.key_fifths)
  const [mode, setMode] = useState(analysis.key_mode === 'minor' ? 'minor' : 'major')
  const [time, setTime] = useState(analysis.time ?? '4/4')
  const [clef, setClef] = useState('')
  const [title, setTitle] = useState(analysis.title)
  const [composer, setComposer] = useState(analysis.composer)
  const review = recognition?.review
  const summary = review?.summary
  const issues = review?.items ?? []
  const srcName = source?.id === 'custom' ? 'Custom instrument' : instruments.find((i) => i.id === source?.id)?.name

  const save = async () => {
    if (key !== analysis.key_fifths || (mode === 'minor') !== (analysis.key_mode === 'minor')) {
      await onCorrect({ op: 'set_key', measure_index: 0, fifths: key, mode })
    }
    if (time !== analysis.time) {
      const [b, t] = time.split('/').map(Number)
      if (b && t) await onCorrect({ op: 'set_time', measure_index: 0, beats: b, beat_type: t })
    }
    if (title !== analysis.title || composer !== analysis.composer) {
      await onCorrect({ op: 'set_metadata', title, composer })
    }
    if (clef) {
      await onCorrect({ op: 'set_clef', measure_index: 0, staff: 1, clef, part_id: analysis.parts[0]?.id })
    }
    setEditing(false)
  }

  return (
    <section className="card" aria-labelledby="analysis-h">
      <div className="card-head">
        <h2 id="analysis-h">Detected</h2>
        <button className="btn btn-sm" onClick={() => setEditing(!editing)} disabled={busy}>
          {editing ? 'Cancel' : 'Edit detected information'}
        </button>
      </div>
      {recognition?.engine && <p className="small muted">Source: {recognition.engine}</p>}
      {recognition?.merge?.applied && <p className="small muted">{recognition.merge.summary}</p>}
      {!editing ? (
        <dl className="facts">
          <dt>Title</dt><dd>{analysis.title || <em className="muted">not found — add it with “Edit detected information”</em>}</dd>
          <dt>Composer</dt><dd>{analysis.composer || <em className="muted">not found</em>}</dd>
          <dt>Original instrument</dt><dd>{srcName ?? <em className="muted">not selected</em>}</dd>
          <dt>Clef</dt><dd>{analysis.clef}</dd>
          <dt>Key signature</dt><dd>{analysis.key}{analysis.key_changes.length > 0 && <span className="muted small"> (+{analysis.key_changes.length} change{analysis.key_changes.length > 1 ? 's' : ''})</span>}</dd>
          <dt>Time signature</dt><dd>{analysis.time ?? '—'}</dd>
          <dt>Tempo</dt><dd>{analysis.tempo ? `${analysis.tempo} BPM` : '—'}</dd>
          <dt>Measures</dt><dd>{analysis.measures}</dd>
          {analysis.multirests?.length > 0 && <><dt>Multi-measure rests</dt><dd>{analysis.multirests.map((r) => `${r.bars} bars (m. ${r.measure})`).join(', ')}</dd></>}
          <dt>Detected notes</dt><dd>{analysis.notes} <span className="muted small">({analysis.rests} rests, {analysis.chords} chords, {analysis.voices} voice{analysis.voices !== 1 ? 's' : ''})</span></dd>
          {pageCount > 0 && <><dt>Pages</dt><dd>{pageCount}</dd></>}
          <dt>Parts</dt><dd>{analysis.parts.map((p) => p.name || p.id).join(', ')}</dd>
          {summary && <><dt>Confidence</dt><dd><strong>{pct(summary.overall)}</strong></dd></>}
        </dl>
      ) : (
        <div className="edit-detected">
          <div className="grid-2">
            <label>Title<input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} /></label>
            <label>Composer<input value={composer} onChange={(e) => setComposer(e.target.value)} maxLength={300} /></label>
            <label>Key signature
              <select value={key} onChange={(e) => setKey(Number(e.target.value))}>
                {KEYS.map(([f, n]) => <option key={f} value={f}>{n}</option>)}
              </select>
            </label>
            <label>Mode
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="major">major</option><option value="minor">minor</option>
              </select>
            </label>
            <label>Time signature
              <select value={time} onChange={(e) => setTime(e.target.value)}>
                {['2/4', '3/4', '4/4', '5/4', '6/4', '2/2', '3/2', '3/8', '6/8', '9/8', '12/8', '5/8', '7/8'].map((t) => <option key={t}>{t}</option>)}
              </select>
            </label>
            <label>Clef (first staff)
              <select value={clef} onChange={(e) => setClef(e.target.value)}>
                <option value="">keep ({analysis.clef})</option>
                {clefs.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
              </select>
            </label>
          </div>
          <p className="small muted">Changes apply from the first measure and are recorded as corrections (undoable). The original file is never modified.</p>
          <button className="btn btn-primary btn-sm" onClick={save} disabled={busy}>Apply corrections</button>
        </div>
      )}

      {summary && (
        <div className="confidence-grid" aria-label="Recognition confidence">
          {([['Notes', summary.notes], ['Rhythm', summary.rhythm], ['Clef', summary.clef], ['Key signature', summary.key], ['Time signature', summary.time]] as const).map(([l, v]) => (
            <div key={l} className={`conf ${v != null && review && v < review.threshold ? 'low' : ''}`}><span>{l}</span><strong>{pct(v)}</strong></div>
          ))}
        </div>
      )}
      {recognition?.warnings?.map((w, i) => <div key={i} className="alert alert-warn small">{w}</div>)}
      {issues.length > 0 ? (
        <div className="alert alert-warn">
          Some notation could not be confidently recognized.{' '}
          <button className="btn btn-sm" onClick={onReview}>Review {issues.length} issue{issues.length > 1 ? 's' : ''}</button>
        </div>
      ) : (
        recognition && <p className="small ok-text">✓ No recognition issues need review.</p>
      )}
    </section>
  )
}
