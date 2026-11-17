from __future__ import annotations

import os
from dataclasses import dataclass


RETENTION_KEEP = "keep"
RETENTION_DELETE_AFTER_EXTRACT = "delete_after_extract"


@dataclass(frozen=True)
class AttachmentConfig:
    """Limits and behavior switches for attachment processing."""

    max_bytes: int = 20 * 1024 * 1024
    max_pages: int = 50
    max_text_chars: int = 200_000
    spreadsheet_row_cap: int = 500
    segment_chars: int = 3500
    segment_overlap: int = 200
    min_segment_chars: int = 20
    timeout_seconds: int = 60
    # Run parsers in a child process so a crash/hang cannot take down the caller.
    isolate: bool = True
    # keep | delete_after_extract
    retention: str = RETENTION_KEEP
    # A document listing this many flat/unit references is treated as a resident listing.
    flat_listing_threshold: int = 8
    # none | local (RapidOCR). OCR never sends content to an external provider.
    ocr_backend: str = "none"
    ocr_min_confidence: float = 0.6
    ocr_max_pages: int = 10
    ocr_timeout_seconds: int = 180
    # Pages with fewer native-text characters than this are OCR candidates.
    ocr_page_min_chars: int = 25
    # Images with a shorter side below this (icons, stickers) are not worth OCR.
    ocr_min_image_side: int = 200
    # OCR output shorter than this marks the image as no_text (photo, meme, selfie).
    ocr_min_text_chars: int = 30

    @classmethod
    def from_env(cls) -> "AttachmentConfig":
        """Build a config from APTJEEVES_ATTACHMENT_* environment variables."""

        defaults = cls()
        retention = os.environ.get("APTJEEVES_ATTACHMENT_RETENTION", defaults.retention).strip().lower()
        if retention not in {RETENTION_KEEP, RETENTION_DELETE_AFTER_EXTRACT}:
            retention = RETENTION_KEEP
        ocr_backend = os.environ.get("APTJEEVES_ATTACHMENT_OCR_BACKEND", defaults.ocr_backend).strip().lower()
        if ocr_backend not in {"none", "local"}:
            ocr_backend = "none"
        return cls(
            max_bytes=_env_int("APTJEEVES_ATTACHMENT_MAX_BYTES", defaults.max_bytes),
            max_pages=_env_int("APTJEEVES_ATTACHMENT_MAX_PAGES", defaults.max_pages),
            max_text_chars=_env_int("APTJEEVES_ATTACHMENT_MAX_TEXT_CHARS", defaults.max_text_chars),
            timeout_seconds=_env_int("APTJEEVES_ATTACHMENT_TIMEOUT_SECONDS", defaults.timeout_seconds),
            retention=retention,
            ocr_backend=ocr_backend,
            ocr_min_confidence=_env_float("APTJEEVES_ATTACHMENT_OCR_MIN_CONFIDENCE", defaults.ocr_min_confidence),
            ocr_max_pages=_env_int("APTJEEVES_ATTACHMENT_OCR_MAX_PAGES", defaults.ocr_max_pages),
            ocr_timeout_seconds=_env_int("APTJEEVES_ATTACHMENT_OCR_TIMEOUT_SECONDS", defaults.ocr_timeout_seconds),
            ocr_min_image_side=_env_int("APTJEEVES_ATTACHMENT_OCR_MIN_IMAGE_SIDE", defaults.ocr_min_image_side),
            ocr_min_text_chars=_env_int("APTJEEVES_ATTACHMENT_OCR_MIN_TEXT_CHARS", defaults.ocr_min_text_chars),
            flat_listing_threshold=_env_int(
                "APTJEEVES_ATTACHMENT_FLAT_LISTING_THRESHOLD", defaults.flat_listing_threshold
            ),
        )


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if 0.0 <= value <= 1.0 else default
