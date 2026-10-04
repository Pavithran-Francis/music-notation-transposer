import { useRef, useState } from 'react'

const ACCEPT = '.pdf,.png,.jpg,.jpeg,.musicxml,.xml,.mxl,.mscz,application/pdf,image/png,image/jpeg'

interface Props {
  onFiles: (files: File[]) => void
  busy: boolean
  uploading?: boolean
  maxMb: number
  currentFile?: string | null
}

export function UploadArea({ onFiles, busy, uploading, maxMb, currentFile }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)

  const pick = (list: FileList | null) => {
    if (!list || list.length === 0) return
    onFiles(Array.from(list))
  }

  return (
    <div
      className={`dropzone ${over ? 'over' : ''} ${busy ? 'busy' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setOver(true) }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); if (!busy) pick(e.dataTransfer.files) }}
    >
      <input ref={input} type="file" accept={ACCEPT} multiple hidden onChange={(e) => { pick(e.target.files); e.target.value = '' }} />
      <p className="drop-title">{uploading ? 'Uploading…' : busy ? 'Processing…' : 'Drag & drop a PDF, image or MusicXML file'}</p>
      <p className="muted small">
        PDF, PNG, JPG · MusicXML (.musicxml, .xml, .mxl) · MuseScore (.mscz) · up to {maxMb} MB.
        Select several images for a multi-page score.
      </p>
      <button className="btn" disabled={busy} onClick={() => input.current?.click()}>
        {currentFile ? 'Replace file…' : 'Choose file…'}
      </button>
      {currentFile && <p className="small current-file">Current: <strong>{currentFile}</strong></p>}
    </div>
  )
}
