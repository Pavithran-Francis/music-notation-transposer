import { useEffect, useRef, useState } from 'react'
import { api, type NoteDetails } from '../services/api'

const TYPES = ['whole', 'half', 'quarter', 'eighth', '16th', '32nd', '64th']

interface Props {
  projectId: string
  noteId: string
  onApply: (ops: Record<string, unknown>[]) => Promise<void>
  onClose: () => void
}

/** Edit a recognized note: pitch, accidental, octave, duration, rest. */
export function NoteEditor({ projectId, noteId, onApply, onClose }: Props) {
  const [note, setNote] = useState<NoteDetails | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [step, setStep] = useState('C')
  const [alter, setAlter] = useState(0)
  const [octave, setOctave] = useState(4)
  const [type, setType] = useState('quarter')
  const [dots, setDots] = useState(0)
  const [isRest, setIsRest] = useState(false)
  const [saving, setSaving] = useState(false)
  const dialog = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.note(projectId, noteId, 'original').then((n) => {
      setNote(n)
      setStep(n.step ?? 'C'); setAlter(n.alter ?? 0); setOctave(n.octave ?? 4)
      setType(n.type ?? 'quarter'); setDots(n.dots); setIsRest(n.is_rest)
    }).catch((e) => setError(e.message))
  }, [projectId, noteId])

  useEffect(() => {
    dialog.current?.focus()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const apply = async () => {
    if (!note) return
    const ops: Record<string, unknown>[] = []
    if (isRest && !note.is_rest) ops.push({ op: 'to_rest', note_id: noteId })
    else if (!isRest && note.is_rest) ops.push({ op: 'to_note', note_id: noteId, step, alter, octave })
    else if (!isRest && (step !== note.step || alter !== note.alter || octave !== note.octave)) {
      ops.push({ op: 'set_pitch', note_id: noteId, step, alter, octave })
    }
    if (type !== note.type || dots !== note.dots) ops.push({ op: 'set_duration', note_id: noteId, type, dots })
    if (ops.length === 0) return onClose()
    setSaving(true)
    try {
      await onApply(ops)
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="note-editor-h" tabIndex={-1} ref={dialog}
        onClick={(e) => e.stopPropagation()}>
        <h2 id="note-editor-h">Correct note</h2>
        {!note && !error && <p>Loading…</p>}
        {error && <p className="error-text" role="alert">{error}</p>}
        {note && (
          <>
            <p className="small muted">
              Measure {note.measure}, beat {Number(note.beat.toFixed(2))}, voice {note.voice}
              {note.confidence != null && <> · recognition confidence <strong>{Math.round(note.confidence * 100)}%</strong></>}
              <br />Detected: <strong>{note.is_rest ? 'rest' : note.pitch}</strong> ({note.type ?? '?'}{note.dots ? ' dotted' : ''})
            </p>
            <label className="check"><input type="checkbox" checked={isRest} disabled={note.is_chord}
              onChange={(e) => setIsRest(e.target.checked)} /> <span>Rest</span></label>
            {!isRest && (
              <div className="grid-3">
                <label>Note
                  <select value={step} onChange={(e) => setStep(e.target.value)}>
                    {'CDEFGAB'.split('').map((s) => <option key={s}>{s}</option>)}
                  </select>
                </label>
                <label>Accidental
                  <select value={alter} onChange={(e) => setAlter(Number(e.target.value))}>
                    <option value={-2}>𝄫 double flat</option><option value={-1}>♭ flat</option>
                    <option value={0}>♮ natural</option><option value={1}>♯ sharp</option><option value={2}>𝄪 double sharp</option>
                  </select>
                </label>
                <label>Octave
                  <select value={octave} onChange={(e) => setOctave(Number(e.target.value))}>
                    {[1, 2, 3, 4, 5, 6, 7].map((o) => <option key={o}>{o}</option>)}
                  </select>
                </label>
              </div>
            )}
            <div className="grid-3">
              <label>Duration
                <select value={type} onChange={(e) => setType(e.target.value)}>
                  {TYPES.map((t) => <option key={t}>{t}</option>)}
                </select>
              </label>
              <label>Dots
                <select value={dots} onChange={(e) => setDots(Number(e.target.value))}>
                  {[0, 1, 2].map((d) => <option key={d}>{d}</option>)}
                </select>
              </label>
            </div>
            {note.is_chord && (
              <button className="btn btn-sm danger" disabled={saving}
                onClick={async () => { setSaving(true); try { await onApply([{ op: 'delete_chord_note', note_id: noteId }]); onClose() } catch (e) { setError((e as Error).message) } finally { setSaving(false) } }}>
                Remove this note from the chord
              </button>
            )}
          </>
        )}
        <div className="modal-actions">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={apply} disabled={!note || saving}>{saving ? 'Saving…' : 'Apply'}</button>
        </div>
      </div>
    </div>
  )
}
