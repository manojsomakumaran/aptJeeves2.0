from __future__ import annotations

from aptjeeves.ingestion.hashing import sha256_text


def conversation_id(*, platform: str, chat_name: str) -> str:
    """Create a stable conversation identity from source platform and chat name."""

    return sha256_text(f"{platform.strip().casefold()}\n{chat_name.strip().casefold()}")


def message_fingerprint(
    *,
    platform: str,
    source_conversation_id: str,
    source_message_id: str | None,
    canonical_sender: str,
    sent_at_utc: str,
    normalized_text_hash: str,
    attachment_hashes_or_markers: str = "",
) -> str:
    """Create the durable identity used to dedupe imported chat messages.

    Native source message IDs are preferred when a platform provides them. Text
    exports often do not, so the fallback combines conversation, sender,
    timestamp, normalized text hash, and attachment markers. This is stronger
    than sender + datetime and stays stable across repeated full-history imports.
    """

    if source_message_id:
        # Native IDs are assumed to be stable within a source conversation and
        # avoid collisions between identical messages sent at the same time.
        return sha256_text(
            "\n".join(
                [
                    platform.strip().casefold(),
                    source_conversation_id,
                    source_message_id.strip(),
                ]
            )
        )

    # Keep separators explicit so accidental concatenation cannot create the
    # same byte string from different field combinations.
    return sha256_text(
        "\n".join(
            [
                platform.strip().casefold(),
                source_conversation_id,
                canonical_sender,
                sent_at_utc,
                normalized_text_hash,
                attachment_hashes_or_markers,
            ]
        )
    )
