"""OMR engine interface. The rest of the app never talks to a concrete engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ProgressCallback = Callable[[str, str, float], None]  # (step, message, fraction 0..1)


class OMRError(RuntimeError):
    """Recognition failed; message is shown to the user."""


@dataclass
class OMRResult:
    musicxml: bytes
    engine: str
    page_count: int
    # Per-page list of measure records used to attach confidence to notes.
    # Shape is engine specific but consumed through `confidence_for_score`.
    raw_confidence: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    # Present when a second engine's reading was merged in (see core.omr_merge).
    merge: dict | None = None
    # Multi-measure rests found, with the count read from the page image.
    multirests: list[dict] = field(default_factory=list)


class OMREngine(ABC):
    name: str = "engine"

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def recognize(self, pages: list[Path], workdir: Path, progress: ProgressCallback,
                  source_pdf: Path | None = None) -> OMRResult:
        """Recognize the given preprocessed page images (in order) into MusicXML.

        `source_pdf`, when given, is the untouched original PDF with exactly these
        pages; engines that render PDFs themselves get better input from it.
        """

    def describe(self) -> dict:
        return {"name": self.name, "available": self.is_available()}
