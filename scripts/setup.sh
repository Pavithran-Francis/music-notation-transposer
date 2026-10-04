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

echo "==> Checking external tools"
backend/.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, "backend")
from app.config import get_settings
s = get_settings()
print("  Audiveris:", s.resolved_audiveris() or "NOT FOUND (PDF/image recognition disabled; MusicXML still works)")
print("  MuseScore:", s.resolved_mscore() or "not found (PDFs will be engraved with Verovio instead)")
PY
echo "Done. Start with: scripts/dev.sh"
