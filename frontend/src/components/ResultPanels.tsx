import { useState } from 'react'
import { api, type Result } from '../services/api'

export function TranspositionSummary({ result }: { result: Result }) {
  const t = result.transposition
  const keyChange = t.key_changes[0]
  const clefs = [...new Set(result.clef_changes.map((c) => c.label))]
  return (
    <section className="card" aria-labelledby="sum-h">
      <h2 id="sum-h">Transposition</h2>
      <dl className="facts">
        <dt>From → to</dt><dd>{result.source.name} → <strong>{result.target.name}</strong></dd>
        <dt>Written interval</dt><dd>{t.interval_description} <span className="muted small">({t.interval}, {t.semitones > 0 ? '+' : ''}{t.semitones} semitones)</span></dd>
        {keyChange && <><dt>Key signature</dt><dd>{keyChange.from} → <strong>{keyChange.to}</strong>{t.key_changes.length > 1 && <span className="muted small"> (+{t.key_changes.length - 1} more)</span>}</dd></>}
        <dt>Clef{clefs.length > 1 ? 's' : ''}</dt><dd>{clefs.join(', ') || '—'}{result.clef_changes.length > clefs.length && <span className="muted small"> ({result.clef_changes.length} clef changes)</span>}</dd>
        <dt>Rhythm</dt><dd>Unchanged</dd>
      </dl>
      {t.warnings.map((w, i) => <div key={i} className="alert alert-warn small">{w}</div>)}
    </section>
  )
}

interface RangeProps {
  projectId: string
  result: Result
  selected: string[]
  onResult: (r: Result) => void
  onSelect: (ids: string[]) => void
}

export function RangePanel({ projectId, result, selected, onResult, onSelect }: RangeProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const r = result.range
  const run = async (fn: () => Promise<{ result: Result }>) => {
    setBusy(true); setError(null)
    try { onResult((await fn()).result) } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  const pending = r.issues.filter((i) => !i.acknowledged)
  const ids = selected.length ? selected : pending.map((i) => i.note_id)

  return (
    <section className="card" aria-labelledby="range-h">
      <h2 id="range-h">Range check</h2>
      <p className="small muted">Typical written range of the {result.target.name}: {r.target_range}</p>
      {r.outside_typical === 0 ? (
        <p className="ok-text">✓ All notes are within the typical range of the {result.target.name}.</p>
      ) : (
        <div className={`alert ${pending.length ? 'alert-warn' : 'alert-info'}`} role="status">
          <strong>Warning:</strong> the transposed score contains {r.outside_typical} note{r.outside_typical > 1 ? 's' : ''} outside the typical range of the selected instrument
          {r.outside_extended > 0 && <> ({r.outside_extended} beyond its extended range)</>}. They are highlighted in red.
          {pending.length === 0 && <> You chose to keep them as they are.</>}
        </div>
      )}
      {r.outside_typical > 0 && (
        <>
          <div className="row wrap">
            <button className="btn btn-sm" disabled={busy} onClick={() => run(() => api.rangeAction(projectId, 'keep', ids))}>Keep original pitch</button>
            <button className="btn btn-sm" disabled={busy} onClick={() => run(() => api.rangeAction(projectId, 'move', ids, 1))}>Move octave up</button>
            <button className="btn btn-sm" disabled={busy} onClick={() => run(() => api.rangeAction(projectId, 'move', ids, -1))}>Move octave down</button>
            <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => run(() => api.rangeAction(projectId, 'auto'))}>Attempt automatic range correction</button>
          </div>
          <p className="small muted">{selected.length ? `${selected.length} note(s) selected.` : 'Actions apply to all flagged notes; select individual notes below or click them in the preview.'}</p>
          <ul className="issue-list">
            {r.issues.map((i) => (
              <li key={i.note_id}>
                <label className="check">
                  <input type="checkbox" checked={selected.includes(i.note_id)}
                    onChange={(e) => onSelect(e.target.checked ? [...selected, i.note_id] : selected.filter((x) => x !== i.note_id))} />
                  <span>m. {i.measure}, beat {Number(i.beat.toFixed(2))}: <strong>{i.pitch}</strong> — too {i.direction}
                    {i.severity === 'outside_extended' && <span className="tag tag-red">beyond extended range</span>}
                    {i.acknowledged && <span className="tag">kept</span>}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </>
      )}
      {result.actions.length > 0 && (
        <div className="adjustments">
          <div className="card-head">
            <h3>Adjustments ({result.octave_shifts} note{result.octave_shifts !== 1 ? 's' : ''} moved)</h3>
            <button className="btn btn-sm" disabled={busy} onClick={() => run(() => api.undoRange(projectId))}>Undo last</button>
          </div>
          <ol className="small">
            {result.actions.map((a) => (
              <li key={a.id}>
                <strong>{a.label}</strong>
                <ul>{result.adjustments.filter((x) => x.action_id === a.id).map((x, k) => <li key={k}>{x.description}</li>)}</ul>
              </li>
            ))}
          </ol>
          <p className="small muted">Moved notes are shown in blue.</p>
        </div>
      )}
      {error && <p className="error-text" role="alert">{error}</p>}
    </section>
  )
}

export function ValidationPanel({ result }: { result: Result }) {
  const v = result.validation
  return (
    <section className="card" aria-labelledby="val-h">
      <h2 id="val-h">Score validation</h2>
      <p className={v.passed ? 'ok-text' : 'error-text'}><strong>{v.passed ? '✓ ' : '✗ '}{v.summary}</strong></p>
      <ul className="checks small">
        {v.checks.map((c) => (
          <li key={c.name} className={c.passed ? 'pass' : 'fail'}>
            <span aria-hidden="true">{c.passed ? '✓' : '✗'}</span> {c.name}{c.detail && <span className="muted"> — {c.detail}</span>}
          </li>
        ))}
      </ul>
      {v.issues.length > 0 && (
        <details>
          <summary className="small">{v.issues.length} detail{v.issues.length > 1 ? 's' : ''}</summary>
          <ul className="small">{v.issues.map((i, k) => <li key={k} className={i.severity === 'error' ? 'error-text' : ''}>{i.message}</li>)}</ul>
        </details>
      )}
    </section>
  )
}

export function ExportPanel({ projectId, result, stale }: { projectId: string; result: Result; stale: boolean }) {
  const [format, setFormat] = useState<'pdf' | 'musicxml' | 'midi' | 'png' | 'svg'>('pdf')
  const labels = { pdf: 'PDF (engraved)', musicxml: 'MusicXML (opens in MuseScore)', midi: 'MIDI (concert pitch)', png: 'PNG (page 1)', svg: 'SVG (page 1)' }
  return (
    <section className="card" aria-labelledby="exp-h">
      <h2 id="exp-h">Download</h2>
      {stale && <div className="alert alert-warn small">Settings or corrections changed since this result was generated. Click “Transpose” again to update it.</div>}
      <div className="row wrap">
        <a className="btn btn-primary" href={api.exportUrl(projectId, 'pdf')} download>Download PDF</a>
        <a className="btn" href={api.exportUrl(projectId, 'musicxml')} download>Download MusicXML</a>
        <a className="btn" href={api.exportUrl(projectId, 'midi')} download>Download MIDI</a>
      </div>
      <div className="row wrap" style={{ marginTop: 8 }}>
        <label className="sr-only" htmlFor="fmt">Other format</label>
        <select id="fmt" value={format} onChange={(e) => setFormat(e.target.value as typeof format)}>
          {Object.entries(labels).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <a className="btn btn-sm" href={api.exportUrl(projectId, format)} download>Download</a>
      </div>
      <p className="small muted">
        {result.pdf_engine ? `PDF engraved with ${result.pdf_engine}` : 'PDF engraved on download'}
        {result.pdf_pages ? ` · ${result.pdf_pages} page${result.pdf_pages > 1 ? 's' : ''}` : ''}. MIDI contains sounding (concert) pitch.
      </p>
    </section>
  )
}
