// Typed client for the backend REST API (see http://localhost:8000/docs).

export interface Instrument {
  id: string
  name: string
  family: string
  clefs: string[]
  clef_labels: string[]
  transposition: string
  transposition_description: string
  range_low: string
  range_high: string
  ext_low: string | null
  ext_high: string | null
  staves: number
  key_name: string
  notes: string
}

export interface CustomInstrumentSpec {
  id: 'custom'
  name: string
  interval: string
  direction: 'up' | 'down'
  octave_displacement: number
  clef: string
  range_low: string
  range_high: string
  staves: number
}

export type InstrumentSpec = { id: string } | CustomInstrumentSpec

export interface Job {
  id: string
  project_id: string
  kind: 'analyze' | 'transpose'
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  step: string
  message: string
  progress: number
  error: string | null
}

export interface PartInfo {
  id: string
  name: string
  staves: number
  measures: number
  notes: number
  clefs: string[]
  transposition: string
  instrument_guess: string | null
  lowest: string | null
  highest: string | null
}

export interface Analysis {
  title: string
  composer: string
  parts: PartInfo[]
  key: string
  key_fifths: number
  key_mode: string
  time: string | null
  clef: string
  tempo: number | null
  measures: number
  notes: number
  rests: number
  chords: number
  voices: number
  key_changes: { measure: string; key: string }[]
  time_changes: { measure: string; time: string | null }[]
  features: Record<string, number>
  multirests: { part_id: string; measure: string; bars: number }[]
}

export interface ReviewItem {
  kind: 'note' | 'measure' | 'header'
  note_id?: string
  part_id?: string
  measure?: string
  measure_index?: number
  beat?: number
  detected?: string
  duration?: string
  confidence: number | null
  reason: string
  field?: string
  severity?: string
}

export interface Recognition {
  engine: string | null
  warnings: string[]
  merge?: { applied: boolean; summary: string; reason: string } | null
  pages: { index: number; blank: boolean; warnings: string[]; actions: string[] }[]
  review?: {
    items: ReviewItem[]
    threshold: number
    summary: null | {
      overall: number
      notes: number
      rhythm: number
      clef: number | null
      key: number | null
      time: number | null
      low_confidence_notes: number
      mapping: string
    }
  }
}

export interface RangeIssue {
  note_id: string
  part_id: string
  measure: string
  beat: number
  pitch: string
  direction: 'high' | 'low'
  severity: 'outside_typical' | 'outside_extended'
  suggested_octaves: number
  acknowledged: boolean
}

export interface Adjustment {
  action_id: number
  action: string
  kind: 'global' | 'note'
  octaves: number
  note_ids?: string[]
  description: string
}

export interface ValidationReport {
  passed: boolean
  summary: string
  checks: { name: string; passed: boolean; detail: string }[]
  issues: { severity: string; code: string; message: string; measure?: string; note_id?: string }[]
}

export interface Result {
  transposition: {
    interval: string
    interval_description: string
    semitones: number
    key_changes: { measure: string; from: string; to: string }[]
    warnings: string[]
    respelled_notes: number
  }
  source: Instrument
  target: Instrument
  clef_changes: { measure: string; staff: number; label: string }[]
  range: {
    issues: RangeIssue[]
    outside_typical: number
    outside_extended: number
    unacknowledged: number
    target_range: string
  }
  adjustments: Adjustment[]
  actions: { id: number; kind: string; label: string }[]
  octave_shifts: number
  validation: ValidationReport
  analysis: Analysis
  pdf_engine?: string
  pdf_pages?: number
}

export interface Settings {
  key_preference?: 'auto' | 'sharps' | 'flats'
  courtesy_accidentals?: boolean
  optimize_range?: boolean
  simplify_double_accidentals?: boolean
  part_ids?: string[] | null
}

export interface Project {
  id: string
  name: string
  saved: boolean
  status: string
  created_at: string
  updated_at: string
  source_kind: 'pdf' | 'image' | 'musicxml' | 'mscz' | null
  original_filename: string | null
  page_count: number
  source_instrument: InstrumentSpec | null
  target_instrument: InstrumentSpec | null
  error: string | null
  has_result: boolean
  result_stale: boolean
  settings?: Settings
  page_rotations?: number[]
  corrections?: Record<string, unknown>[]
  analysis?: Analysis | null
  recognition?: Recognition | null
  result?: Result | null
  job?: Job | null
}

export interface NoteDetails {
  note_id: string
  part_id: string
  measure: string
  measure_index: number
  beat: number
  staff: number
  voice: string
  is_rest: boolean
  is_chord: boolean
  pitch: string | null
  step: string | null
  alter: number
  octave: number | null
  type: string | null
  dots: number
  confidence: number | null
}

export interface Health {
  status: string
  omr: { engine: string; available: boolean; secondary: string | null; ocr_languages: string[] }
  musescore: { available: boolean }
  renderer: string
  limits: { max_upload_mb: number; max_pdf_pages: number }
  retention_hours: number
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} }
  if (body instanceof FormData) {
    init.body = body
  } else if (body !== undefined) {
    init.body = JSON.stringify(body)
    ;(init.headers as Record<string, string>)['Content-Type'] = 'application/json'
  }
  let res: Response
  try {
    res = await fetch(url, init)
  } catch {
    throw new ApiError(0, 'Cannot reach the server. Is the backend running?')
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }
  if (!res.ok) {
    const detail = (data as { detail?: unknown })?.detail
    const msg = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((d) => d.msg).join('; ') : `Request failed (${res.status})`
    throw new ApiError(res.status, msg)
  }
  return data as T
}

const P = (id: string) => `/api/projects/${id}`

export const api = {
  health: () => request<Health>('GET', '/api/health'),
  instruments: () => request<{ instruments: Instrument[]; clefs: { id: string; label: string }[] }>('GET', '/api/instruments'),
  validateInstrument: (spec: CustomInstrumentSpec) => request<Instrument>('POST', '/api/instruments/validate', spec),

  listProjects: () => request<{ projects: Project[] }>('GET', '/api/projects'),
  createProject: (name = 'Untitled score') => request<Project>('POST', '/api/projects', { name }),
  getProject: (id: string) => request<Project>('GET', P(id)),
  updateProject: (id: string, patch: Partial<Pick<Project, 'name' | 'saved' | 'source_instrument' | 'target_instrument' | 'settings'>>) =>
    request<Project>('PATCH', P(id), patch),
  deleteProject: (id: string) => request<void>('DELETE', P(id)),
  duplicateProject: (id: string) => request<Project>('POST', `${P(id)}/duplicate`),
  history: (id: string) => request<{ history: { at: string; action: string; detail: Record<string, unknown> }[] }>('GET', `${P(id)}/history`),

  upload: (id: string, files: File[]) => {
    const fd = new FormData()
    files.forEach((f) => fd.append('files', f))
    return request<Project>('POST', `${P(id)}/upload`, fd)
  },
  rotatePage: (id: string, page: number, degrees: number) =>
    request<{ page_rotations: number[] }>('POST', `${P(id)}/pages/${page}/rotate`, { degrees }),
  thumbnailUrl: (id: string, page: number, bust = 0) => `${P(id)}/pages/${page}/thumbnail?v=${bust}`,

  analyze: (id: string) => request<{ job_id: string }>('POST', `${P(id)}/analyze`),
  correction: (id: string, op: Record<string, unknown>) => request<unknown>('PATCH', `${P(id)}/corrections`, op),
  undoCorrection: (id: string) => request<unknown>('DELETE', `${P(id)}/corrections/last`),
  note: (id: string, noteId: string, which: 'original' | 'result') =>
    request<NoteDetails>('GET', `${P(id)}/notes/${encodeURIComponent(noteId)}?which=${which}`),

  transpose: (id: string, body: { source_instrument: InstrumentSpec; target_instrument: InstrumentSpec; settings: Settings }) =>
    request<{ job_id: string }>('POST', `${P(id)}/transpose`, body),
  rangeAction: (id: string, action: 'auto' | 'move' | 'keep', note_ids?: string[], octaves = 0) =>
    request<{ result: Result }>('POST', `${P(id)}/range`, { action, note_ids, octaves }),
  undoRange: (id: string) => request<{ result: Result }>('DELETE', `${P(id)}/range/last`),

  previewInfo: (id: string, which: 'original' | 'result') => request<{ pages: number }>('GET', `${P(id)}/preview?which=${which}`),
  previewPage: async (id: string, which: 'original' | 'result', page: number) => {
    const res = await fetch(`${P(id)}/preview/${which}/${page}`)
    if (!res.ok) throw new ApiError(res.status, 'Preview unavailable')
    return res.text()
  },
  exportUrl: (id: string, format: 'pdf' | 'musicxml' | 'midi' | 'png' | 'svg', which: 'original' | 'result' = 'result', page = 1) =>
    `${P(id)}/export/${format}?which=${which}&page=${page}`,

  job: (jobId: string) => request<Job>('GET', `/api/jobs/${jobId}`),
}
