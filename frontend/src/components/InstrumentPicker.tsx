import { useEffect, useMemo, useState } from 'react'
import { api, type CustomInstrumentSpec, type Instrument, type InstrumentSpec } from '../services/api'

interface Props {
  id: string
  label: string
  instruments: Instrument[]
  clefs: { id: string; label: string }[]
  value: InstrumentSpec | null
  onChange: (spec: InstrumentSpec) => void
  hint?: string | null
  disabled?: boolean
}

const DEFAULT_CUSTOM: CustomInstrumentSpec = {
  id: 'custom', name: 'Custom instrument', interval: 'M2', direction: 'down', octave_displacement: 0,
  clef: 'treble', range_low: 'C3', range_high: 'C7', staves: 1,
}

const INTERVALS = [
  ['P1', 'Unison (non-transposing)'], ['m2', 'Minor 2nd'], ['M2', 'Major 2nd'], ['m3', 'Minor 3rd'], ['M3', 'Major 3rd'],
  ['P4', 'Perfect 4th'], ['A4', 'Augmented 4th'], ['P5', 'Perfect 5th'], ['m6', 'Minor 6th'], ['M6', 'Major 6th'],
  ['m7', 'Minor 7th'], ['M7', 'Major 7th'],
]

export function InstrumentPicker({ id, label, instruments, clefs, value, onChange, hint, disabled }: Props) {
  const families = useMemo(() => {
    const m = new Map<string, Instrument[]>()
    instruments.forEach((i) => m.set(i.family, [...(m.get(i.family) ?? []), i]))
    return [...m.entries()]
  }, [instruments])

  const isCustom = value?.id === 'custom'
  const [custom, setCustom] = useState<CustomInstrumentSpec>(isCustom ? (value as CustomInstrumentSpec) : DEFAULT_CUSTOM)
  const [customInfo, setCustomInfo] = useState<string | null>(null)
  const [customError, setCustomError] = useState<string | null>(null)

  useEffect(() => {
    if (!isCustom) return
    const t = window.setTimeout(() => {
      api.validateInstrument(custom)
        .then((inst) => { setCustomError(null); setCustomInfo(inst.transposition_description); onChange(custom) })
        .catch((e) => { setCustomInfo(null); setCustomError(e.message) })
    }, 300)
    return () => window.clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [custom, isCustom])

  const selected = instruments.find((i) => i.id === value?.id)
  const set = <K extends keyof CustomInstrumentSpec>(k: K, v: CustomInstrumentSpec[K]) => setCustom({ ...custom, [k]: v })

  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        value={value?.id ?? ''}
        disabled={disabled}
        onChange={(e) => (e.target.value === 'custom' ? onChange(custom) : onChange({ id: e.target.value }))}
      >
        <option value="" disabled>Select instrument…</option>
        {families.map(([family, list]) => (
          <optgroup key={family} label={family}>
            {list.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
          </optgroup>
        ))}
        <option value="custom">Custom instrument…</option>
      </select>
      {hint && <p className="small muted">{hint}</p>}
      {selected && (
        <p className="small muted">
          {selected.transposition_description} · {selected.clef_labels.join(' / ')} clef · written range {selected.range_low}–{selected.range_high}
          {selected.notes ? ` · ${selected.notes}` : ''}
        </p>
      )}
      {isCustom && (
        <fieldset className="custom-instrument" disabled={disabled}>
          <legend className="small">Custom instrument settings</legend>
          <div className="grid-2">
            <label>Name<input value={custom.name} onChange={(e) => set('name', e.target.value)} /></label>
            <label>Transposition interval
              <select value={custom.interval} onChange={(e) => set('interval', e.target.value)}>
                {INTERVALS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
            <label>Sounds
              <select value={custom.direction} onChange={(e) => set('direction', e.target.value as 'up' | 'down')}>
                <option value="down">below written pitch</option>
                <option value="up">above written pitch</option>
              </select>
            </label>
            <label>Octave displacement
              <select value={custom.octave_displacement} onChange={(e) => set('octave_displacement', Number(e.target.value))}>
                {[-2, -1, 0, 1, 2].map((o) => <option key={o} value={o}>{o === 0 ? 'none' : `${o > 0 ? '+' : ''}${o} octave${Math.abs(o) > 1 ? 's' : ''}`}</option>)}
              </select>
            </label>
            <label>Clef
              <select value={custom.clef} onChange={(e) => set('clef', e.target.value)}>
                {clefs.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
              </select>
            </label>
            <label>Written range
              <span className="range-inputs">
                <input aria-label="Lowest written note" value={custom.range_low} onChange={(e) => set('range_low', e.target.value)} size={4} />
                –
                <input aria-label="Highest written note" value={custom.range_high} onChange={(e) => set('range_high', e.target.value)} size={4} />
              </span>
            </label>
          </div>
          {customInfo && <p className="small muted">{customInfo}</p>}
          {customError && <p className="small error-text" role="alert">{customError}</p>}
        </fieldset>
      )}
    </div>
  )
}
