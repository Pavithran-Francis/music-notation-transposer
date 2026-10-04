"""Application settings (environment variables prefixed with SMT_)."""

from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


def _first_existing(candidates: list[str | Path | None]) -> str | None:
    for c in candidates:
        if not c:
            continue
        p = Path(c)
        if p.exists():
            return str(p)
        found = shutil.which(str(c))
        if found:
            return found
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SMT_", env_file=str(BACKEND_DIR / ".env"), extra="ignore")

    data_dir: Path = BACKEND_DIR / "data"
    max_upload_mb: int = 50
    max_pdf_pages: int = 40
    max_image_pixels: int = 80_000_000
    retention_hours: int = 24  # unsaved projects are deleted after this long
    cleanup_interval_minutes: int = 30
    workers: int = 2
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    audiveris_path: str | None = None
    audiveris_timeout_per_page: int = 180
    mscore_path: str | None = None
    mscore_timeout: int = 180
    omr_confidence_threshold: float = 0.75
    render_dpi: int = 300

    def resolved_audiveris(self) -> str | None:
        return _first_existing([
            self.audiveris_path,
            REPO_DIR / "tools/Audiveris.app/Contents/MacOS/Audiveris",
            "/Applications/Audiveris.app/Contents/MacOS/Audiveris",
            "/opt/audiveris/bin/Audiveris",
            "audiveris",
            "Audiveris",
        ])

    def resolved_mscore(self) -> str | None:
        return _first_existing([
            self.mscore_path,
            "/Applications/MuseScore 4.app/Contents/MacOS/mscore",
            "/Applications/MuseScore 3.app/Contents/MacOS/mscore",
            "mscore4portable",
            "mscore4",
            "musescore4",
            "mscore",
            "musescore",
            "mscore3",
        ])

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s
