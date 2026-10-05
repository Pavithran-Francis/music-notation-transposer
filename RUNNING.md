# Running the Sheet Music Transposer

All commands are run from the project root:
`/Users/pavithranfrancis/Documents/PaviDev/music-notation-transposer`

## First-time setup (once per machine)

```bash
scripts/setup.sh
```

This script does three things:
- creates the Python environment in `backend/.venv`
- installs the frontend packages
- downloads Audiveris (the music-recognition engine) into `tools/` on macOS
- installs Audiveris's English OCR data, needed for titles and other text
- installs homr, the second recognition engine, into `tools/homr-venv`

At the end it prints whether Audiveris and MuseScore were found.

On this Mac it has already been done. Only re-run it after cloning the repo somewhere new, or if you delete `backend/.venv` or `frontend/node_modules`.

## Start (development)

**Option A: one command, both servers**

```bash
scripts/dev.sh
```

Stop both with `Ctrl+C`.

**Option B: two terminals**

```bash
# Terminal 1 — backend (API)
cd backend
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Terminal 2 — frontend (UI)
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

Stop each with `Ctrl+C`.

| What | URL |
|---|---|
| The app | http://127.0.0.1:5173 |
| API documentation (Swagger) | http://127.0.0.1:8000/docs |
| Health check (shows if Audiveris/MuseScore are detected) | http://127.0.0.1:8000/api/health |

## Start (production-style, single server)

```bash
scripts/serve.sh            # builds the UI, then serves UI + API at http://localhost:8000
PORT=9000 scripts/serve.sh  # different port
```

## Measure recognition accuracy

```bash
cd backend
.venv/bin/python -m benchmarks.make_benchmark   # (re)creates the benchmark scores with MuseScore
.venv/bin/python -m benchmarks.compare          # Audiveris vs homr vs merged, on clean PDFs and degraded scans
.venv/bin/python -m benchmarks.run YOUR.pdf TRUTH.musicxml   # score any document against its known MusicXML
```

## Run the tests

```bash
scripts/test.sh                                         # backend tests + frontend type-check + lint
cd backend && .venv/bin/python -m pytest -q -p no:warnings   # backend only
```

## Docker (alternative)

Docker Desktop must be running.

```bash
docker compose up --build   # http://localhost:8000
docker compose down         # stop
```

## Troubleshooting

| Problem | Fix |
|---|---|
| "Address already in use" | Something is still running. Run `lsof -i :8000 -i :5173` to find it, then `kill <PID>`, or `pkill -f "uvicorn app.main:app"; pkill -f vite` |
| App says "Cannot reach the server" | The backend isn't running. Start it (Terminal 1 above) |
| Header shows "No OCR text" | Audiveris has no OCR language, so titles and text are lost. Run `scripts/setup.sh` |
| Header shows "OMR: Audiveris" without "+ homr" | The second engine isn't installed; accuracy is lower. Run `scripts/setup.sh` |
| Header shows "OMR: not installed" | Audiveris isn't found. Run `scripts/setup.sh` or set `SMT_AUDIVERIS_PATH` in `backend/.env` |
| PDFs say "engraved with Verovio" | MuseScore wasn't found. Install MuseScore 4 or set `SMT_MSCORE_PATH` |
| Start completely fresh (deletes all projects) | Stop the servers, then `rm -rf backend/data` |

---

# What's still needed from you

The app works end-to-end on this machine. These are the things only you can do or decide.

## 1. Test with your own real sheet music (most important)

**The best help you can give:** a PDF or photo of a page that comes out wrong, together with its MusicXML if you
have it (e.g. exported from MuseScore). I can then add it to the benchmark (`benchmarks.run your.pdf truth.musicxml`)
and fix what it reveals, with measurements rather than guesses.

Testing so far used scores engraved by MuseScore. You need to run your real material through it:
- a scanned page
- a phone photo of a page
- a PDF from a publisher or IMSLP
- a multi-page part
- your own MuseScore exports (MusicXML)

For each one:
- check how many items the review step flags and whether the corrections are easy to make
- open the downloaded MusicXML in the **MuseScore app** and compare it with the original

Tell me what goes wrong (wrong notes, missed symbols, bad layout) and I can tune it.

## 2. Check the instruments you actually use

The list is in `backend/core/instruments/database.py`. Please confirm:
- the instruments you need are there
- the ranges match your players. The defaults are typical textbook ranges; student players often have narrower ones.

Anything missing can be added there, or used through "Custom instrument" in the UI.

## 3. Decide where it will run

| If you want… | You need to… |
|---|---|
| Just you, on this Mac | Nothing more. Use `scripts/dev.sh` or `scripts/serve.sh` |
| Others on your network or the internet | Choose a host (VPS, home server…). Put it behind HTTPS (Caddy or nginx) **and a login**: the app has no user accounts. |
| Docker deployment | Start Docker Desktop and run `docker compose up --build` once to verify the image. It has **not** been built yet. On Apple Silicon it runs emulated (amd64) and recognition will be slower. |

## 4. Licensing, if you ever share or host it publicly

Some components are copyleft. That is fine for personal use, but it matters if you publish the app or offer it as a service:
- **Audiveris**, **homr** and **PyMuPDF** are AGPL. If you run the app as a public web service, you must make the source code available to its users. PyMuPDF also offers a commercial licence.
- **MuseScore** is GPL. It is used as a separate external program, not bundled into the code.

Decide whether that's acceptable, or ask me to swap components.

## 5. Put the code somewhere safe

The repository is committed locally but has **no remote**. To back it up on GitHub:

```bash
gh repo create music-notation-transposer --private --source=. --push
```

## 6. Choose what to build next (optional)

These are known limitations (see README → Known limitations). Pick which matter to you:
- **Splitting multi-staff scores:** piano → single-line instrument currently keeps both staves; it could extract or reduce one part.
- **Upside-down pages:** detection of pages rotated 180° (today you use the rotate buttons).
- **Text recognition:** reading tempo marks, titles and part names, which Audiveris often misses.
- **Transposing by any interval:** e.g. "up a minor third", independent of instruments.
- **Partial transposition:** only selected measures.
- **Batch mode:** many files at once.
- **User accounts:** if others will use it.

## 7. Small settings you may want to change (`backend/.env`)

Copy `backend/.env.example` to `backend/.env` and adjust:
- `SMT_RETENTION_HOURS`: unsaved projects are deleted after 24 h by default. Click **Save** on any project you want to keep.
- `SMT_MAX_UPLOAD_MB` and `SMT_MAX_PDF_PAGES`: raise these if your scores are larger.
- `SMT_OMR_CONFIDENCE_THRESHOLD`: lower it for fewer review flags, raise it to be stricter.
