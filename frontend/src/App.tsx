import { useCallback, useEffect, useRef, useState } from 'react'
import { Sidebar } from './components/Sidebar'
import { Workspace } from './pages/Workspace'
import { api, type Health, type Instrument, type Project } from './services/api'

const LAST_KEY = 'smt:lastProject'

export default function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [current, setCurrent] = useState<Project | null>(null)
  const [instruments, setInstruments] = useState<Instrument[]>([])
  const [clefs, setClefs] = useState<{ id: string; label: string }[]>([])
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showPrivacy, setShowPrivacy] = useState(false)

  const initialized = useRef(false)

  const loadList = useCallback(async () => setProjects((await api.listProjects()).projects), [])

  const open = useCallback(async (id: string) => {
    try {
      setCurrent(await api.getProject(id))
      localStorage.setItem(LAST_KEY, id)
    } catch (e) {
      setError((e as Error).message)
      localStorage.removeItem(LAST_KEY)
    }
  }, [])

  const newProject = useCallback(async () => {
    const p = await api.createProject()
    await loadList()
    await open(p.id)
  }, [loadList, open])

  useEffect(() => {
    if (initialized.current) return // StrictMode runs effects twice in development
    initialized.current = true
    ;(async () => {
      try {
        const [inst, h] = await Promise.all([api.instruments(), api.health()])
        setInstruments(inst.instruments)
        setClefs(inst.clefs)
        setHealth(h)
        const list = (await api.listProjects()).projects
        setProjects(list)
        const last = localStorage.getItem(LAST_KEY)
        if (last && list.some((p) => p.id === last)) await open(last)
        else if (list.length) await open(list[0].id)
        else await newProject()
      } catch (e) {
        setError((e as Error).message)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const refresh = useCallback(async () => {
    if (current) await open(current.id)
    await loadList()
  }, [current, open, loadList])

  return (
    <div className="app">
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="header">
        <div className="brand">
          <img src="/favicon.svg" alt="" width={28} height={28} />
          <h1>Sheet Music Transposer</h1>
        </div>
        <div className="header-right small">
          {health && (
            <span className="status-pills">
              <span className={`pill ${health.omr.available ? 'ok' : 'bad'}`}>OMR: {health.omr.available ? health.omr.engine : 'not installed'}</span>
              {health.omr.available && health.omr.ocr_languages.length === 0 && (
                <span className="pill bad" title="Install OCR language data (scripts/setup.sh) so titles and text are recognized">No OCR text</span>
              )}
              <span className="pill ok">Engraving: {health.renderer}</span>
            </span>
          )}
          <button className="link" onClick={() => setShowPrivacy(!showPrivacy)} aria-expanded={showPrivacy}>Privacy</button>
        </div>
      </header>
      {showPrivacy && (
        <div className="privacy" role="note">
          Your files are processed only on this server and are never used for training. Unsaved projects and their files
          are deleted automatically after {health?.retention_hours ?? 24} hours; click <em>Save</em> on a project to keep it.
          Deleting a project removes all of its files immediately.
        </div>
      )}
      {error && <div className="alert alert-error" role="alert">{error}</div>}
      <div className="layout">
        <Sidebar
          projects={projects}
          currentId={current?.id ?? null}
          onOpen={open}
          onNew={() => newProject().catch((e) => setError(e.message))}
          onRename={async (id, name) => { await api.updateProject(id, { name }); await refresh() }}
          onDelete={async (id) => {
            await api.deleteProject(id)
            const list = (await api.listProjects()).projects
            setProjects(list)
            if (current?.id === id) {
              if (list.length) await open(list[0].id)
              else await newProject()
            }
          }}
          onDuplicate={async (id) => { const p = await api.duplicateProject(id); await loadList(); await open(p.id) }}
          onToggleSaved={async (id, saved) => { await api.updateProject(id, { saved }); await refresh() }}
        />
        <main id="main" className="main">
          {current ? (
            <Workspace project={current} instruments={instruments} clefs={clefs} health={health} onChanged={refresh} />
          ) : (
            !error && <p className="muted">Loading…</p>
          )}
        </main>
      </div>
    </div>
  )
}
