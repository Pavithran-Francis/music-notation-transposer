#!/usr/bin/env bash
# One-time local setup: Python env, frontend deps, Audiveris (macOS arm64/x86_64).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Backend virtualenv"
PY=${PYTHON:-$(command -v python3.12 || command -v python3.11 || command -v python3)}
"$PY" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
"$PY" -m venv backend/.venv
backend/.venv/bin/pip install -q --upgrade pip
backend/.venv/bin/pip install -q -r backend/requirements.txt

echo "==> Frontend dependencies"
(cd frontend && npm install --silent)

if [[ "$(uname)" == "Darwin" && ! -d tools/Audiveris.app && ! -d /Applications/Audiveris.app ]]; then
  echo "==> Downloading Audiveris (OMR engine) into tools/"
  ARCH=$( [[ "$(uname -m)" == "arm64" ]] && echo arm64 || echo x86_64 )
  VER=5.11.0
  mkdir -p tools
  curl -fL -o tools/Audiveris.dmg "https://github.com/Audiveris/audiveris/releases/download/${VER}/Audiveris-${VER}-macosx-${ARCH}.dmg"
  MNT=$(mktemp -d)
  yes | hdiutil attach -nobrowse -readonly -mountpoint "$MNT" tools/Audiveris.dmg >/dev/null
  cp -R "$MNT/Audiveris.app" tools/
  hdiutil detach "$MNT" >/dev/null
  rm tools/Audiveris.dmg
  xattr -dr com.apple.quarantine tools/Audiveris.app 2>/dev/null || true
fi

echo "==> OCR language data for Audiveris (titles, tempo text, lyrics)"
TESS=$(backend/.venv/bin/python -c 'import sys; sys.path.insert(0,"backend"); from app.config import Settings; print(Settings.audiveris_tessdata_dir())')
mkdir -p "$TESS"
[[ -f "$TESS/eng.traineddata" ]] || curl -fL -o "$TESS/eng.traineddata" https://github.com/tesseract-ocr/tessdata/raw/main/eng.traineddata

echo "==> Second OMR engine (homr) in tools/homr-venv"
if [[ ! -x tools/homr-venv/bin/homr ]]; then
  "$PY" -m venv tools/homr-venv
  tools/homr-venv/bin/pip install -q --upgrade pip
  tools/homr-venv/bin/pip install -q "homr==0.7.0"
fi
tools/homr-venv/bin/homr --init >/dev/null 2>&1 || echo "  (homr model download failed; recognition will use Audiveris only)"

echo "==> Checking external tools"
backend/.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, "backend")
from app.config import get_settings
s = get_settings()
print("  Audiveris:", s.resolved_audiveris() or "NOT FOUND (PDF/image recognition disabled; MusicXML still works)")
print("  homr:     ", s.resolved_homr() or "not found (single-engine recognition)")
print("  OCR langs:", ", ".join(s.ocr_languages()) or "NONE (titles/text will not be recognized)")
print("  MuseScore:", s.resolved_mscore() or "not found (PDFs will be engraved with Verovio instead)")
PY
echo "Done. Start with: scripts/dev.sh"
