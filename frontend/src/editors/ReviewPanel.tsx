import type { ReviewItem } from '../services/api'

interface Props {
  items: ReviewItem[]
  corrections: number
  onSelectNote: (noteId: string) => void
  onUndo: () => void
  onClose: () => void
  busy: boolean
}

export function ReviewPanel({ items, corrections, onSelectNote, onUndo, onClose, busy }: Props) {
  return (
    <section className="card review" aria-labelledby="review-h">
      <div className="card-head">
        <h2 id="review-h">Review recognition</h2>
        <div className="row">
          <button className="btn btn-sm" onClick={onUndo} disabled={busy || corrections === 0}>Undo last correction</button>
          <button className="btn btn-sm" onClick={onClose}>Done</button>
        </div>
      </div>
      <p className="small muted">
        Only uncertain items are listed. Click an item (or any note in the recognized score) to correct it.
        Uncertain notes are <span className="swatch orange" /> orange / <span className="swatch red" /> red in the preview; corrected notes turn <span className="swatch green" /> green.
      </p>
      {items.length === 0 ? <p className="ok-text">✓ Nothing left to review.</p> : (
        <table className="table">
          <thead><tr><th>Measure</th><th>Beat</th><th>Detected</th><th>Confidence</th><th>Issue</th><th /></tr></thead>
          <tbody>
            {items.map((it, i) => (
              <tr key={i}>
                <td>{it.measure ?? (it.kind === 'header' ? 1 : '—')}</td>
                <td>{it.beat != null ? Number(it.beat.toFixed(2)) : '—'}</td>
                <td>{it.detected ?? it.field ?? '—'}{it.duration ? <span className="muted small"> ({it.duration})</span> : null}</td>
                <td>{it.confidence != null ? `${Math.round(it.confidence * 100)}%` : '—'}</td>
                <td className="small">{it.reason}</td>
                <td>{it.note_id && <button className="btn btn-sm" onClick={() => onSelectNote(it.note_id!)}>Edit</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
