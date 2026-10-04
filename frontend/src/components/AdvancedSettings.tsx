import type { PartInfo, Settings } from '../services/api'

interface Props {
  settings: Settings
  parts: PartInfo[]
  onChange: (s: Settings) => void
  disabled?: boolean
}

export function AdvancedSettings({ settings, parts, onChange, disabled }: Props) {
  const set = (patch: Partial<Settings>) => onChange({ ...settings, ...patch })
  const selectedParts = settings.part_ids ?? parts.map((p) => p.id)

  return (
    <details className="advanced">
      <summary>Advanced settings</summary>
      <fieldset disabled={disabled}>
        <label className="check">
          <input type="checkbox" checked={!!settings.optimize_range} onChange={(e) => set({ optimize_range: e.target.checked })} />
          <span>
            <strong>Optimize for target instrument</strong>
            <span className="small muted block">Move notes by octaves when needed to fit the instrument's range. Every adjustment is listed and can be undone.</span>
          </span>
        </label>
        <label className="check">
          <input type="checkbox" checked={settings.courtesy_accidentals ?? true} onChange={(e) => set({ courtesy_accidentals: e.target.checked })} />
          <span>Add courtesy accidentals in the measure after a chromatic note</span>
        </label>
        <label className="check">
          <input type="checkbox" checked={!!settings.simplify_double_accidentals} onChange={(e) => set({ simplify_double_accidentals: e.target.checked })} />
          <span>Respell double sharps/flats as simpler notes</span>
        </label>
        <div className="field inline">
          <label htmlFor="keypref">Enharmonic key preference</label>
          <select id="keypref" value={settings.key_preference ?? 'auto'} onChange={(e) => set({ key_preference: e.target.value as Settings['key_preference'] })}>
            <option value="auto">Automatic (fewest accidentals)</option>
            <option value="sharps">Prefer sharp keys</option>
            <option value="flats">Prefer flat keys</option>
          </select>
        </div>
        {parts.length > 1 && (
          <div className="field">
            <span className="label">Parts to transpose</span>
            {parts.map((p) => (
              <label key={p.id} className="check">
                <input
                  type="checkbox"
                  checked={selectedParts.includes(p.id)}
                  onChange={(e) => {
                    const next = e.target.checked ? [...selectedParts, p.id] : selectedParts.filter((x) => x !== p.id)
                    set({ part_ids: next.length === parts.length ? null : next })
                  }}
                />
                <span>{p.name || p.id} <span className="muted small">({p.staves} staff{p.staves > 1 ? 's' : ''}, {p.notes} notes)</span></span>
              </label>
            ))}
          </div>
        )}
      </fieldset>
    </details>
  )
}
