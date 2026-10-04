import { useState } from 'react'
import type { Project } from '../services/api'

interface Props {
  projects: Project[]
  currentId: string | null
  onOpen: (id: string) => void
  onNew: () => void
  onRename: (id: string, name: string) => void
  onDelete: (id: string) => void
  onDuplicate: (id: string) => void
  onToggleSaved: (id: string, saved: boolean) => void
}

const STATUS_LABEL: Record<string, string> = {
  created: 'New', uploaded: 'Uploaded', analyzing: 'Analyzing…', analyzed: 'Analyzed',
  transposing: 'Transposing…', transposed: 'Transposed', failed: 'Needs attention',
}

export function Sidebar({ projects, currentId, onOpen, onNew, onRename, onDelete, onDuplicate, onToggleSaved }: Props) {
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  return (
    <aside className="sidebar" aria-label="Projects">
      <div className="sidebar-head">
        <h2>Projects</h2>
        <button className="btn btn-primary btn-sm" onClick={onNew}>+ New project</button>
      </div>
      {projects.length === 0 && <p className="muted small">No projects yet.</p>}
      <ul className="project-list">
        {projects.map((p) => (
          <li key={p.id} className={p.id === currentId ? 'active' : ''}>
            {editing === p.id ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  onRename(p.id, draft)
                  setEditing(null)
                }}
              >
                <label className="sr-only" htmlFor={`rename-${p.id}`}>Project name</label>
                <input id={`rename-${p.id}`} autoFocus value={draft} onChange={(e) => setDraft(e.target.value)}
                  onBlur={() => { onRename(p.id, draft); setEditing(null) }}
                  onKeyDown={(e) => e.key === 'Escape' && setEditing(null)} />
              </form>
            ) : (
              <button className="project-open" onClick={() => onOpen(p.id)} aria-current={p.id === currentId}>
                <span className="project-name">{p.name}</span>
                <span className="project-meta">
                  {STATUS_LABEL[p.status] ?? p.status}
                  {p.saved ? ' · Saved' : ''}
                </span>
              </button>
            )}
            {p.id === currentId && editing !== p.id && (
              <div className="project-actions">
                <button className="link" onClick={() => { setDraft(p.name); setEditing(p.id) }}>Rename</button>
                <button className="link" onClick={() => onDuplicate(p.id)}>Duplicate</button>
                <button className="link" onClick={() => onToggleSaved(p.id, !p.saved)}>{p.saved ? 'Unsave' : 'Save'}</button>
                {confirmDelete === p.id ? (
                  <>
                    <button className="link danger" onClick={() => { onDelete(p.id); setConfirmDelete(null) }}>Confirm delete</button>
                    <button className="link" onClick={() => setConfirmDelete(null)}>Cancel</button>
                  </>
                ) : (
                  <button className="link danger" onClick={() => setConfirmDelete(p.id)}>Delete</button>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
    </aside>
  )
}
