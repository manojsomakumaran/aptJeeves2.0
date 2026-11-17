"""Local-only OCR. No image or document content ever leaves the machine.

The backend is optional (``pip install .[ocr]``) and imported lazily so the
core install stays light. Callers get plain ``(text, confidence)`` lines.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

OCR_NONE = "none"
OCR_LOCAL = "local"


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float


class OcrBackend(Protocol):
    def read_image(self, path: Path) -> list[OcrLine]: ...

    def read_bytes(self, data: bytes) -> list[OcrLine]: ...


class OcrUnavailableError(Exception):
    """The OCR engine is not installed."""


class RapidOcrBackend:
    """RapidOCR (ONNX runtime) backend; the engine is built on first use."""

    def __init__(self) -> None:
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as exc:
                raise OcrUnavailableError("rapidocr_onnxruntime is not installed") from exc
            self._engine = RapidOCR()
        return self._engine

    def read_image(self, path: Path) -> list[OcrLine]:
        return self.read_bytes(path.read_bytes())

    def read_bytes(self, data: bytes) -> list[OcrLine]:
        result, _elapsed = self._get_engine()(data)
        lines: list[OcrLine] = []
        for item in result or []:
            # item = [box, text, score]
            text = str(item[1]).strip()
            if text:
                lines.append(OcrLine(text=text, confidence=float(item[2])))
        return lines


_backend_override: OcrBackend | None = None


def set_backend_override(backend: OcrBackend | None) -> None:
    """Test hook: force a specific backend in this process."""

    global _backend_override
    _backend_override = backend


def get_backend(name: str) -> OcrBackend | None:
    if _backend_override is not None:
        return _backend_override
    if name == OCR_LOCAL:
        return RapidOcrBackend()
    return None


def lines_to_text(lines: list[OcrLine], min_confidence: float) -> tuple[str, float]:
    """Keep confident lines; return (text, mean confidence of kept lines)."""

    kept = [line for line in lines if line.confidence >= min_confidence]
    if not kept:
        return "", 0.0
    return "\n".join(line.text for line in kept), sum(l.confidence for l in kept) / len(kept)
