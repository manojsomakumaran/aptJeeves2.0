from __future__ import annotations

from aptjeeves.ingestion.normalizer import normalize_timestamp


def test_normalize_timestamp_uses_configured_timezone() -> None:
    assert (
        normalize_timestamp(
            "16/04/26",
            "9:30 PM",
            default_timezone="Asia/Kolkata",
            date_order="DMY",
        )
        == "2026-04-16T16:00:00Z"
    )
