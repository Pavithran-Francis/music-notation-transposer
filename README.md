# Sheet Music Transposer

Upload sheet music (PDF, PNG/JPG, MusicXML or MuseScore), have it recognized as real musical notation,
and get a correctly transposed, professionally engraved score for another instrument — as PDF,
MusicXML (opens directly in MuseScore) and MIDI.

```
Upload → choose original instrument → choose target instrument → analyze → review → transpose → preview → download
```

The application does **not** treat sheet music as text. Every page is converted into structured
notation (MusicXML) first; transposition operates on pitches, intervals and key signatures; and the
result is re-engraved from the transposed MusicXML.

---

## Contents

1. [Quick start](#quick-start)
2. [Installation](#installation)
3. [Development](#development)
4. [Production deployment](#production-deployment)
5. [Configuration (environment variables)](#configuration)
6. [Architecture](#architecture)
7. [OMR engine](#omr-engine-optical-music-recognition)
8. [Transposition algorithm](#transposition-algorithm)
9. [Rendering pipeline](#rendering-pipeline)
10. [API](#api)
11. [Database schema & storage](#database-schema--storage)
12. [Testing](#testing)
13. [Security & privacy](#security--privacy)
14. [Known limitations](#known-limitations)
15. [Future improvements](#future-improvements)

---

## Quick start

```bash
scripts/setup.sh     # Python venv, npm install, downloads Audiveris (macOS) into tools/
scripts/dev.sh       # backend on :8000, frontend on :5173
```

Open http://127.0.0.1:5173. Try `samples/little-waltz-flute.pdf` (a printed one-page score) or
`samples/little-waltz-flute.musicxml`.

## Installation

| Requirement | Why | Notes |
|---|---|---|
| Python 3.11+ | backend | `scripts/setup.sh` creates `backend/.venv` and installs `backend/requirements.txt` |
| Node.js 20+ | frontend build | Vite + React + TypeScript |
| **Audiveris 5.x** | OMR for PDF / images | Bundles its own Java runtime. Optional: without it, MusicXML/MuseScore uploads still work |
| Tesseract `eng.traineddata` | Audiveris text OCR (titles, tempo text, lyrics) | Placed in Audiveris's `tessdata` folder by `scripts/setup.sh` |
| **homr 0.7** (optional) | second OMR engine (ensemble) | Installed by `scripts/setup.sh` into `tools/homr-venv` (~420 MB incl. models) |
| **MuseScore 4 (or 3)** | best PDF engraving, `.mscz` import | Optional: without it PDFs are engraved by Verovio |
| Cairo (`libcairo2` / `brew install cairo`) | Verovio PDF fallback | Used only when MuseScore is not installed |

**Audiveris**
- macOS: `scripts/setup.sh` downloads the official `.dmg` and copies `Audiveris.app` into `tools/`.
  Nothing is installed system-wide. Alternatively, install it into `/Applications`.
- Linux: `sudo apt install ./Audiveris-5.11.0-ubuntu24.04-x86_64.deb` from the
  [releases page](https://github.com/Audiveris/audiveris/releases). It installs to `/opt/audiveris/bin/Audiveris`.
- Windows: use the `windowsConsole` `.msi` and set `SMT_AUDIVERIS_PATH`.

**MuseScore**: install from https://musescore.org. It is auto-detected in `/Applications` and on
`PATH` (`mscore`, `mscore4`, `musescore`, `mscore3`). On Linux it runs headless with `QT_QPA_PLATFORM=offscreen`.

Check what was detected: `curl http://127.0.0.1:8000/api/health`. The app header also shows it.

## Development

```bash
scripts/dev.sh                 # both servers with hot reload
# or separately:
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev     # proxies /api to :8000
scripts/test.sh                # backend tests + frontend type-check + lint
```

Code layout:

```
backend/
  core/                     pure musical logic — no web, no I/O (fully unit-tested)
    music/pitch.py          pitches, diatonic intervals, key signatures, enharmonic choice
    music/clefs.py          clef geometry and ledger-line cost
    instruments/database.py instrument database (transposition, ranges, clefs, MIDI program)
    musicxml/document.py    safe MusicXML parsing (.xml/.mxl), contextual walker, note ids
    transposition/engine.py transposition, accidental display, automatic clef selection
    validation/range.py     range checks, logged octave adjustments, auto range correction
    validation/validator.py rhythmic/structural validation, source↔result comparison
    corrections.py          recognition corrections (replayable edit operations)
    analysis.py             detected key/time/clef/tempo/notes/instrument guess
  app/
    main.py                 FastAPI app (also serves the built frontend)
    api/routes.py           REST endpoints (OpenAPI at /docs)
    services/omr/           OMRService + Audiveris adapter, preprocessing, confidence mapping
    services/rendering/     Verovio SVG, MuseScore/Verovio PDF, PNG, MIDI
    services/pipeline.py    analyze → correct → transpose → range → render orchestration
    services/jobs.py        background job runner + retention cleanup
    services/storage.py     per-project file storage
    db.py, config.py
  tests/                    unit, golden-corpus and API tests (fixtures/ = golden MusicXML)
frontend/src/
  pages/Workspace.tsx       the workflow page
  components/               upload, instruments, settings, analysis, results, sidebar
  editors/                  recognition review + note editor
  viewers/ScoreViewer.tsx   zoomable, paged, clickable SVG score viewer
  services/                 typed API client, job polling hook
```

## Production deployment

**Single process (simplest):**

```bash
scripts/serve.sh   # builds frontend, serves UI + API on :8000 (HOST/PORT env vars)
```

Put it behind a reverse proxy (nginx/Caddy) for TLS. Set `client_max_body_size` to at least `SMT_MAX_UPLOAD_MB`.

**Docker:**

```bash
docker compose up --build      # http://localhost:8000, data in the smt-data volume
```

The image (Ubuntu 24.04) includes Audiveris (`.deb`) and MuseScore 3. Audiveris only ships x86_64
Linux packages, so the image is `linux/amd64`. On Apple Silicon it runs under emulation, and OMR is slower.
*The Dockerfile has not been built in the development environment of this README (Docker was not running there),
so treat it as a starting point and verify the build once.*

Run **one** uvicorn worker: background jobs run in-process and share the SQLite database.
To scale out, swap `services/jobs.submit` for Celery/RQ, the DB URL for PostgreSQL (SQLAlchemy is already
used) and `services/storage.py` for S3-compatible storage. These are the only three seams to change.

## Configuration

All variables are optional (prefix `SMT_`, also read from `backend/.env`; see `backend/.env.example`).

| Variable | Default | Meaning |
|---|---|---|
| `SMT_DATA_DIR` | `backend/data` | SQLite DB + project files |
| `SMT_MAX_UPLOAD_MB` | `50` | per-file upload limit |
| `SMT_MAX_PDF_PAGES` | `40` | max pages per document |
| `SMT_MAX_IMAGE_PIXELS` | `80000000` | decompression-bomb guard |
| `SMT_RETENTION_HOURS` | `24` | unsaved projects are deleted after this |
| `SMT_CLEANUP_INTERVAL_MINUTES` | `30` | cleanup frequency |
| `SMT_WORKERS` | `2` | concurrent background jobs |
| `SMT_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | allowed browser origins (dev) |
| `SMT_AUDIVERIS_PATH` | auto | Audiveris executable |
| `SMT_AUDIVERIS_TIMEOUT_PER_PAGE` | `180` | seconds |
| `SMT_HOMR_PATH` | auto (`tools/homr-venv/bin/homr`) | second OMR engine |
| `SMT_HOMR_TIMEOUT_PER_PAGE` | `300` | seconds |
| `SMT_OMR_ENSEMBLE` | `true` | set `false` to use Audiveris only |
| `SMT_MSCORE_PATH` | auto | MuseScore executable |
| `SMT_MSCORE_TIMEOUT` | `180` | seconds |
| `SMT_OMR_CONFIDENCE_THRESHOLD` | `0.75` | notes below this are listed for review |
| `SMT_RENDER_DPI` | `300` | PDF rasterisation resolution for OMR |

## Architecture

```
PDF / PNG / JPG ─► preprocessing ─► OMR (Audiveris) ─► MusicXML ─┐
MusicXML / .mxl ─────────────────────────────────────────────────┤
.mscz ─► MuseScore CLI ─► MusicXML ──────────────────────────────┤
PDF with embedded MusicXML ─► extracted directly ────────────────┘
                                                                  ▼
                       source.musicxml  (never modified; every note gets a stable id)
                                  │  recognition corrections (replayed edit list, undoable)
                                  ▼
                       corrected.musicxml ─► analysis, validation, review items
                                  │  transposition (pitches, keys, chord symbols, instrument)
                                  ▼
                       transposed_raw.musicxml
                                  │  range adjustments (explicit, logged, undoable)
                                  │  accidental display + automatic clefs
                                  ▼
                       final.musicxml ─► validation ─► SVG preview / PDF / PNG / MIDI
```

Choices, and why:
- **MusicXML DOM editing (lxml) instead of round-tripping through an object model.** The engine changes only
  pitch, key, accidental, clef, transposition and instrument elements. Everything else (dynamics, slurs,
  articulations, lyrics, repeats, endings, codas, rehearsal marks, hairpins, fermatas, tuplets, beams,
  layout) is preserved byte-for-byte. music21 is used only for MIDI export and as an independent cross-check in tests.
- **Jobs in a thread pool with DB-persisted status.** This is the simplest thing that satisfies "don't block
  the browser" for a single-machine deployment. The UI polls `GET /api/jobs/{id}` and shows step-by-step progress
  ("Analyzing page 2 of 4: Recognizing noteheads…").

## OMR engine (Optical Music Recognition)

Recognition uses **two engines and merges their readings**, because each fails in different ways:

| | Audiveris 5.11 (primary) | homr 0.7 (secondary) |
|---|---|---|
| Strengths | text (title, composer, via Tesseract OCR), dynamics, slurs, articulations, rehearsal marks, multi-staff | notes, rhythms, accidentals, whole notes, robust on scans and photos |
| Weaknesses | misses some whole notes and mid-line time signatures, then **drops notes** to fit the wrong meter; misreads clefs on poor scans | ignores most text and markings; only the time-signature *denominator* is reliable; invents measures from courtesy signatures |

Both engines sit behind `OMREngine` (`app/services/omr/base.py`). `OMRService` runs them in parallel, and
`core/omr_merge.py` merges the two readings measure by measure:

- **Alignment.** Measures are aligned by sequence alignment on pitches, and on interval contour too, so a
  clef misread doesn't break it.
- **Phantom measures** are removed. These are empty measures, and courtesy signatures at line ends or line
  headers read as notes. Any key, time or direction they carried moves on to the next measure.
- **Time signatures** are a stateful sweep:
  - Audiveris's signature is kept while its content fills it.
  - homr's denominator change is trusted when Audiveris saw none.
  - Otherwise the signature is inferred from the measure content: five quarter notes over a /4 means 5/4.
- **Key signatures:** an explicit change seen by either engine beats the other's silence. When the engines
  report different keys, the key that makes the notes most diatonic wins.
- **Notes:**
  - Identical readings are accepted.
  - Otherwise the reading that fills the measure wins, or the one that contains notes the other dropped.
  - Then the one that fits the key better.
  - A clef misread is settled by the pitch centre of the measures both engines agree on.
- **Markings.** Everything else (dynamics, text, slurs, hairpins, layout) is kept from Audiveris.

**Multi-measure rests** (the H-bar with a bar count above it) get special handling:
- **The problem.** Both engines see the bar but misread the number: Audiveris reads only single digits, so 12
  becomes 2, and homr guesses.
- **The detector.** `app/services/omr/multirest.py` finds the bars on the page image: a thick bar on the
  staff's middle line, with short serifs and no stems. It reads the count by template matching against music-font
  digits (Bravura and Leland, both SIL OFL and vendored in `app/services/omr/fonts`) plus bold text fonts.
- **Merging.** Each engine's encoding is collapsed to one "rest block" before merging (`core/multirest.py`). The
  block is then expanded to N real measures, marked `<multiple-rest>`, so measure numbers, transposition and MIDI
  stay correct. Counts that couldn't be read from the page are listed for review.
- **Output.** MuseScore engraves the result as multi-measure rests, like a printed part, and the preview shows
  them as H-bars.

**Title, composer, instrument.**
- Title and composer are read by OCR. They appear under *Detected* and can be edited with "Edit detected
  information".
- The transposed part gets a standard header: the title centred, the composer on the right, and the instrument
  name on the left (e.g. "Alto Saxophone in E♭"), as on printed parts.
- The original instrument is suggested from the part name read on the page.
- Scan-specific page size, staff spacing and line breaks are dropped, so the part is laid out cleanly on A4. The
  local file path Audiveris writes into its output is removed.

Hard-evidence fixes are applied silently. Judgement calls (both readings complete but different, or a clef
disagreement) are listed once per measure for review, and every signature correction is listed where it starts.
Multi-staff parts (piano) use Audiveris only. If homr is not installed, recognition falls back to Audiveris alone.

**Measured accuracy.** These figures come from `backend/benchmarks/`: two synthetic scores, each engraved by
MuseScore and also degraded into a "scan" (200 DPI, skewed, blurred, noisy, JPEG). They include meter changes
(4/4, 3/4, 6/8, 9/8, 12/8, 2/2, 5/4, 3/8, C, ¢), key changes up to 5 accidentals, pickups, triplets,
32nds and ledger lines. Rerun with `cd backend && .venv/bin/python -m benchmarks.compare`.

| Input | Audiveris alone | homr alone | Merged |
|---|---|---|---|
| Benchmark 1, clean PDF | 92% notes, 24/31 time sigs | 97%, 10/31 | **100%, 31/31, keys 31/31** |
| Benchmark 1, degraded scan | 86%, 16/31 | 100%, 16/31 | **100%, 31/31, keys 31/31** |
| Benchmark 2, clean PDF | 62%, 5/19 | 32%¹, 6/19 | **100%², 19/19, keys 19/19** |
| Benchmark 2, degraded scan | 40%, 5/19 | 32%¹, 6/19 | **100%², 19/19, keys 19/19** |
| Benchmark 3 (part with 12/4/2-bar rests), clean and scan | 11 of 24 measures (12-bar rest read as 2) | rest counts 8/4/6 | **24/24 measures, 100%, rests 12/4/2** |

¹ homr inserts phantom measures, which shift every following measure in a by-index comparison.
² The scorer reports 98.5%: the single "miss" is an invisible padding rest in the ground-truth file, which is not
printed on the page.

These are synthetic scores. Real publisher scans will score lower, and measuring them is the next step (see RUNNING.md).

Processing steps:
1. **Input.** PDFs are checked for embedded MusicXML attachments, which are used directly with no OMR.
   Otherwise, an untouched PDF is handed to Audiveris directly; it renders vector PDFs best. Pages that needed
   image fixes are passed as a lossless multi-page TIFF. An earlier PDF-rewrapping approach cut accuracy from
   92% to 60%.
2. **Preprocessing** (OpenCV):
   - manual rotation and crop
   - automatic 90° rotation
   - perspective correction for photographs
   - deskew
   - denoise and CLAHE contrast
   - adaptive binarisation for photos
   - resolution normalisation from the detected staff spacing
   - blank-page detection
   - low-resolution warnings
3. **Recognition.** Audiveris (`-batch -export -save`) and homr run in parallel subprocesses with timeouts.
   homr runs from its own virtualenv (`tools/homr-venv`), so its ML dependencies never touch the backend.
4. **OCR.** Audiveris reads text with Tesseract. The English language file must be installed in Audiveris's
   `tessdata` folder; `scripts/setup.sh` does this. Without it, titles, composer and other text are silently
   lost. The app header warns when it's missing.
5. **Confidence.** For each note, the app takes the minimum of the Audiveris grades for its chord, notehead and
   accidental (from the `.omr` project), mapped by measure → voice → time slot. The merge then adjusts it:
   - agreed measures: 0.97
   - resolved by hard evidence: 0.85
   - judgement calls: 0.6, so they're shown for review
6. **Review.** Uncertain measures and notes are listed and highlighted orange or red. Clicking a note opens the
   editor (pitch, accidental, octave, duration, dots, rest, remove from chord), and "Edit detected information"
   fixes the key, time or clef. All corrections are stored as an undoable list and replayed onto the untouched
   original.

## Transposition algorithm

Every instrument stores its transposition as the interval from **written to sounding** pitch (the MusicXML
`<transpose>` convention):

| Instrument | Written C sounds | Transposition |
|---|---|---|
| Bb trumpet, Bb clarinet | Bb (M2 below) | `-M2` |
| Eb alto sax | Eb (M6 below) | `-M6` |
| F horn | F (P5 below) | `-P5` |
| Bb tenor sax | Bb (M9 below) | `-M9` |
| Piccolo | C an octave above | `P8` |

For each note: `source written → (source transposition) → concert pitch → (inverse target transposition) → target written`.
Both steps are **diatonic intervals** (letter distance + semitones), so they compose into one interval,
`source.transposition − target.transposition`. For example, Bb trumpet → Eb alto sax is `−M2 − (−M6) = +P5`.

Applying one diatonic interval to every note preserves all spelling relationships of the original: chromatic
passing notes keep their melodic direction, leading tones stay leading tones, and chords stay spelled as chords.
F♯ up a M2 is G♯, never A♭.

**Enharmonic spelling / key choice.** The only remaining choice is the enharmonic version of the interval
itself (e.g. up a M2 vs. up a d3). This is decided per key-signature region:
- Keep the natural spelling unless it yields more than 6 sharps or flats.
- Otherwise use the enharmonic equivalent with the fewest accidentals.

For example, B major up a M2 would be C♯ major (7♯), so the engine writes D♭ major (5♭); every note follows
consistently. Octave-only transpositions are never respelled. A user preference (auto / sharp keys / flat keys)
breaks ties. Triple accidentals are always simplified; double accidentals optionally.

**Key signatures.** The new key is `old fifths + interval fifths-delta` and is written into every `<key>`
(mid-piece key changes included). A missing key is treated as C major and made explicit.

**Accidentals.** Displayed accidentals are recomputed from scratch with standard rules:
- An accidental lasts to the end of the measure, per staff and per staff position.
- Tied continuations don't repeat it.
- Courtesy accidentals from the source are kept.
- Optionally, a courtesy accidental is added in the measure after a chromatic alteration.

**Clefs.** For each staff, a dynamic program over measures chooses among the target instrument's clefs. It
minimises a superlinear ledger-line cost, with a penalty for each clef change and a small bias towards the primary
clef. So a cello part moves to tenor/treble only for sustained high passages, and cello → violin writes the same
pitches in treble clef.

**Instrument metadata.** The part name and abbreviation, the MIDI program and `<transpose>` are rewritten, so
MuseScore treats the part as the target instrument (concert-pitch toggle and playback work).

**Range.** After transposition every note is checked against the target's typical and extended written ranges.
Out-of-range notes are highlighted, and the user chooses: **Keep original pitch**, **Move octave** (selected
notes, tie chains move together) or **Attempt automatic range correction** (whole-part octave shift if it
helps, then individual notes). "Optimize for target instrument" applies the automatic correction during
transposition. Pitches are never changed silently: every adjustment is listed and can be undone.

**Rhythm** is never touched. Durations, ties, tuplets, beams, voices and chords are carried over unchanged,
and validation proves it.

**Validation** compares source and result note by note:
- measure count
- note count
- duration, type, dots, voice, onset and ties of every note
- the exact semitone shift of every pitch (plus logged octave adjustments)
- rhythmic validity of every measure
- key signature validity
- target instrument metadata

The result is shown as "Score validation passed." or "N issues require review."

## Rendering pipeline

| Output | Engine | Notes |
|---|---|---|
| On-screen preview | Verovio → SVG | fast; MusicXML note ids are preserved so notes are clickable; colours mark uncertain / out-of-range / adjusted notes |
| PDF | **MuseScore CLI** (preferred) | the same engraving the user gets when opening the MusicXML in MuseScore |
| PDF fallback | Verovio SVG → Cairo → PDF | used when MuseScore is unavailable |
| PNG | PDF page rasterised (MuPDF) | |
| SVG | Verovio | |
| MIDI | music21 | score converted to **sounding pitch** first (MusicXML `<transpose>` applied) |
| MusicXML | lxml | internal note ids stripped; opens directly in MuseScore |

Renders are cached by content hash per project.

## API

Interactive OpenAPI documentation: **http://127.0.0.1:8000/docs**.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | engine availability, limits |
| GET | `/api/instruments` | instrument database + clefs |
| POST | `/api/instruments/validate` | validate a custom instrument |
| POST / GET | `/api/projects` | create / list projects |
| GET / PATCH / DELETE | `/api/projects/{id}` | read, rename/save/set instruments & settings, delete |
| POST | `/api/projects/{id}/duplicate` | duplicate |
| GET | `/api/projects/{id}/history` | processing history |
| POST | `/api/projects/{id}/upload` | upload file(s) (multipart `files`) |
| GET | `/api/projects/{id}/pages/{n}/thumbnail` | page preview |
| POST | `/api/projects/{id}/pages/{n}/rotate` | manual rotation |
| POST | `/api/projects/{id}/analyze` | start recognition job → `job_id` |
| GET | `/api/projects/{id}/analysis` | detected information, confidence, review items |
| PATCH | `/api/projects/{id}/corrections` | add a correction |
| DELETE | `/api/projects/{id}/corrections/last` | undo the last correction |
| GET | `/api/projects/{id}/notes/{note_id}` | note details for the editor |
| POST | `/api/projects/{id}/transpose` | start transposition job → `job_id` |
| GET | `/api/projects/{id}/result` | transposition report, range issues, validation |
| POST | `/api/projects/{id}/range` | `keep` / `move` / `auto` range actions |
| DELETE | `/api/projects/{id}/range/last` | undo the last range action |
| GET | `/api/projects/{id}/preview?which=original\|result` | page count |
| GET | `/api/projects/{id}/preview/{which}/{page}` | SVG page |
| GET | `/api/projects/{id}/export/{pdf\|musicxml\|midi\|png\|svg}` | downloads |
| GET | `/api/jobs/{job_id}` | job status / progress |

Example (MusicXML upload, Flute → Alto sax):

```bash
B=http://127.0.0.1:8000/api
P=$(curl -s -XPOST $B/projects | jq -r .id)
curl -s -F files=@samples/little-waltz-flute.musicxml $B/projects/$P/upload >/dev/null
curl -s -XPOST $B/projects/$P/analyze        # poll /api/jobs/<job_id>
curl -s -XPOST $B/projects/$P/transpose -H 'content-type: application/json' \
  -d '{"source_instrument":{"id":"flute"},"target_instrument":{"id":"alto_sax"}}'
curl -s -o out.pdf $B/projects/$P/export/pdf
```

## Database schema & storage

SQLite (`data/app.db`) via SQLAlchemy:

- **projects**: `id`, `name`, `created_at`, `updated_at`, `saved`, `status`
  (created/uploaded/analyzing/analyzed/transposing/transposed/failed), `source_kind`, `original_filename`,
  `page_count`, `page_rotations` (JSON), `source_instrument` / `target_instrument` (JSON: `{"id": …}` or a
  custom spec), `settings` (JSON), `corrections` (JSON list of edit operations), `range_actions` (JSON list of
  logged adjustments), `analysis`, `recognition`, `result` (JSON), `result_stale`, `error`
- **jobs**: `id`, `project_id`, `kind` (analyze/transpose), `status`, `step`, `message`, `progress`, `error`, timestamps
- **history**: `id`, `project_id`, `at`, `action`, `detail` (JSON)

Files live under `data/projects/<id>/`: the original upload, preprocessed pages, thumbnails, the OMR working
directory, `source` / `corrected` / `transposed_raw` / `final` MusicXML, `confidence.json` and the render cache.

## Testing

```bash
scripts/test.sh                     # everything
cd backend && .venv/bin/python -m pytest -q
```

94 automated tests (plus the OMR benchmark in `backend/benchmarks/`):

- **Golden corpus**: 19 cases in `tests/fixtures/golden/`, each an input MusicXML plus a hand-written expected
  MusicXML. They cover C→Bb, C→Eb, Bb→Eb, Eb→Bb, F→Bb, Bb→C, C→F, tenor sax → concert, the key pairs
  C→D, F→G, Bb→C, Eb→F and G→A, enharmonic key choice (B → D♭), chromatic spelling, a minor key, cello → violin
  and bassoon → tenor sax clef changes, chords/triplets/dotted/tied rhythms, and two-staff, two-voice piano.
  Pitches, rhythms, keys and clefs are compared programmatically.
- **Pitch arithmetic**: cross-checked against music21 on random input.
- **Engine**: accidentals, courtesy accidentals, ties, chord symbols, `<transpose>` metadata, round-trip
  identity, part selection, clef DP, microtones, missing key signatures.
- **Range**: detection, global and individual correction, tie chains.
- **Validation**: catches overfull measures, wrong pitches and deleted notes.
- **Corrections, MusicXML safety and analysis**: corrections replay without touching the original; XXE
  entities are not expanded; `.mxl` is supported; analysis is checked.
- **API**: the full workflow, range actions with undo, corrections, upload rejection, project CRUD, PDF,
  MusicXML, PNG and MIDI export. The MIDI test asserts **sounding** pitch.
- **Two-engine merge**: dropped notes under a wrong meter, measures one engine missed, phantom measures,
  key-change evidence, clef misreads, markings preserved, multi-staff fallback.
- **Multi-measure rests and metadata**:
  - collapse and expand for both engines' encodings
  - the page detector reading counts from 2 to 105, while ignoring beams
  - title and composer from credits, the header credits, and the title/composer correction
  - an engraved part with 12/4/2-bar rests, end to end
- **Real OMR end-to-end**: a known score is engraved to PNG by MuseScore, recognized by Audiveris, then
  transposed and validated. This test is skipped when Audiveris or MuseScore is missing.

`regenerate golden files`: `cd backend && .venv/bin/python -m tests.fixtures.make_golden`.

## Security & privacy

**Uploads are untrusted:**
- size limits, plus type detection by magic bytes (not by extension)
- page and pixel limits, password-protected PDF rejection
- `.mxl` zip-bomb guards
- XML parsed with entity resolution, DTD loading and network access disabled
- stored under generated names only
- OMR and rendering run as separate processes with timeouts; nothing from an upload is ever executed

**Files are processed only on your server and never used for training.** Unsaved projects and all their files
are deleted automatically after `SMT_RETENTION_HOURS` (default 24 h). Saved projects are kept until deleted,
and deleting a project removes its files immediately. The UI explains this under *Privacy*.

There are no user accounts; the app is designed as a personal or local tool. Put it behind an authenticating
reverse proxy before exposing it to the internet.

## Known limitations

- **Text and some markings.** Tempo words ("Allegro moderato") are usually not recognized, although the metronome
  mark is. Hairpins and rehearsal marks are often missed on poor scans. These come only from Audiveris; homr
  doesn't read them.
- **The two-engine merge applies to single-staff parts only.** Piano and other multi-staff parts use Audiveris
  alone.
- **OMR accuracy depends on the input.** Clean printed or engraved scores work well. Handwritten music,
  heavily damaged scans and low-resolution photos often don't. Audiveris may also miss text-based elements:
  tempo marks such as "♩ = 96", part names and titles were not recognized in testing. That is why the review
  step exists. For the most accurate results, upload MusicXML exported from MuseScore.
- **Upside-down pages** (180°) are not detected automatically; use the rotate buttons.
- **Multi-staff source → single-staff instrument** (e.g. piano → flute) keeps both staves and warns. There is
  no automatic part extraction or reduction yet.
- **Ornament accidentals** (e.g. on trills) are kept as in the source and flagged for checking.
  Non-traditional key signatures are kept; their notes are still transposed.
- **Tablature and percussion staves** are not transposed.
- **Duration corrections** must be expressible in the score's existing `divisions`; the editor reports
  when they aren't.
- **Concurrency.** One server process; jobs are not distributed (see [Production deployment](#production-deployment)).
- **Docker.** The image targets linux/amd64 and was not built during development.

## Future improvements

The architecture leaves room for these:
- handwritten OMR or alternative engines (new `OMREngine` implementations)
- audio/MIDI → notation as new ingest paths
- transposition by arbitrary interval: the engine already takes any `Interval`; a UI is needed
- transposing selected measures and whole-score multi-instrument transposition
- part extraction and piano reductions
- a full MusicXML editor beyond note corrections
- batch processing and cloud storage (swap the jobs and storage seams)
- accounts and collaboration
- a mobile layout
