import { useEffect, useRef, useState } from 'react'
import { api } from '../services/api'

interface Props {
  projectId: string
  which: 'original' | 'result'
  title: string
  version: string // changes whenever the score changes, to refetch
  scanPages?: number // original side: show uploaded page images as an alternative
  thumbBust?: number
  selectedNoteId?: string | null
  onNoteClick?: (noteId: string) => void
  legend?: React.ReactNode
}

/** Renders engraved SVG pages (Verovio) with zoom, paging and clickable notes. */
export function ScoreViewer({ projectId, which, title, version, scanPages = 0, thumbBust = 0, selectedNoteId, onNoteClick, legend }: Props) {
  const [mode, setMode] = useState<'score' | 'scan'>('score')
  const [pages, setPages] = useState(0)
  const [page, setPage] = useState(1)
  const [svg, setSvg] = useState<string>('')
  const [zoom, setZoom] = useState(1)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (mode !== 'score') return
    let cancelled = false
    setLoading(true)
    setError(null)
    api.previewInfo(projectId, which)
      .then(({ pages: n }) => {
        if (cancelled) return
        setPages(n)
        const p = Math.min(page, n) || 1
        setPage(p)
        return api.previewPage(projectId, which, p).then((s) => !cancelled && setSvg(s))
      })
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false))
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, which, version, mode])

  useEffect(() => {
    if (mode !== 'score' || pages === 0) return
    let cancelled = false
    api.previewPage(projectId, which, page).then((s) => !cancelled && setSvg(s)).catch((e) => setError(e.message))
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page])

  // highlight the selected note
  useEffect(() => {
    const root = box.current
    if (!root) return
    root.querySelectorAll('.selected-note').forEach((el) => el.classList.remove('selected-note'))
    if (selectedNoteId) {
      const el = root.querySelector(`g.note[id="${CSS.escape(selectedNoteId)}"], g.rest[id="${CSS.escape(selectedNoteId)}"]`)
      el?.classList.add('selected-note')
    }
  }, [selectedNoteId, svg])

  const onClick = (e: React.MouseEvent) => {
    if (!onNoteClick) return
    const el = (e.target as Element).closest('g.note, g.rest')
    if (el?.id) onNoteClick(el.id)
  }

  const total = mode === 'scan' ? scanPages : pages
  const current = Math.min(page, Math.max(total, 1))

  return (
    <div className="viewer">
      <div className="viewer-bar">
        <h3>{title}</h3>
        {scanPages > 0 && (
          <div className="segmented" role="group" aria-label="Original view">
            <button aria-pressed={mode === 'scan'} onClick={() => setMode('scan')}>Uploaded</button>
            <button aria-pressed={mode === 'score'} onClick={() => setMode('score')}>Recognized</button>
          </div>
        )}
        <div className="row">
          <button className="icon-btn" onClick={() => setZoom((z) => Math.max(0.4, +(z - 0.2).toFixed(1)))} aria-label="Zoom out">−</button>
          <span className="small zoom-label" aria-live="polite">{Math.round(zoom * 100)}%</span>
          <button className="icon-btn" onClick={() => setZoom((z) => Math.min(3, +(z + 0.2).toFixed(1)))} aria-label="Zoom in">+</button>
        </div>
        <div className="row">
          <button className="icon-btn" disabled={current <= 1} onClick={() => setPage(current - 1)} aria-label="Previous page">‹</button>
          <span className="small">Page {total ? current : 0} / {total}</span>
          <button className="icon-btn" disabled={current >= total} onClick={() => setPage(current + 1)} aria-label="Next page">›</button>
        </div>
      </div>
      {legend && <div className="viewer-legend small">{legend}</div>}
      <div className="viewer-body" aria-busy={loading}>
        {error && <p className="error-text" role="alert">{error}</p>}
        {mode === 'scan' ? (
          <img className="scan" style={{ width: `${zoom * 100}%` }} src={api.thumbnailUrl(projectId, current, thumbBust)} alt={`Uploaded page ${current}`} />
        ) : (
          <div
            ref={box}
            className={`svg-page ${onNoteClick ? 'clickable' : ''}`}
            style={{ width: `${zoom * 100}%` }}
            onClick={onClick}
            role="img"
            aria-label={`${title}, page ${current}`}
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        )}
      </div>
    </div>
  )
}
