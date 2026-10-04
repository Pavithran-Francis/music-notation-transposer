import { api } from '../services/api'

interface Props {
  projectId: string
  pageCount: number
  rotations: number[]
  bust: number
  disabled: boolean
  onRotate: (page: number, degrees: number) => void
  onOpen: (page: number) => void
}

/** Thumbnails of the uploaded pages, with manual rotation before recognition. */
export function PageStrip({ projectId, pageCount, rotations, bust, disabled, onRotate, onOpen }: Props) {
  if (pageCount === 0) return null
  return (
    <div className="page-strip" role="list" aria-label="Uploaded pages">
      {Array.from({ length: pageCount }, (_, i) => i + 1).map((page) => (
        <figure key={page} className="page-thumb" role="listitem">
          <button className="thumb-btn" onClick={() => onOpen(page)} aria-label={`View page ${page}`}>
            <img src={api.thumbnailUrl(projectId, page, bust)} alt={`Page ${page} of the uploaded score`} loading="lazy" />
          </button>
          <figcaption>
            <span>Page {page}{rotations[page - 1] ? ` · ${rotations[page - 1]}°` : ''}</span>
            <span className="thumb-actions">
              <button className="icon-btn" disabled={disabled} onClick={() => onRotate(page, -90)} aria-label={`Rotate page ${page} left`} title="Rotate left">⟲</button>
              <button className="icon-btn" disabled={disabled} onClick={() => onRotate(page, 90)} aria-label={`Rotate page ${page} right`} title="Rotate right">⟳</button>
            </span>
          </figcaption>
        </figure>
      ))}
    </div>
  )
}
