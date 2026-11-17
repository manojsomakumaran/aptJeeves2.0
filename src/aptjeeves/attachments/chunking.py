from __future__ import annotations


def split_text(text: str, max_chars: int, overlap: int = 0) -> list[str]:
    """Split text into chunks of at most ``max_chars`` on line boundaries.

    Over-long lines are hard-split. Each chunk after the first starts with up to
    ``overlap`` characters of whole trailing lines from the previous chunk.
    """

    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    overlap = max(0, min(overlap, max_chars // 2))
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    lines: list[str] = []
    for line in text.split("\n"):
        while len(line) > max_chars:
            lines.append(line[:max_chars])
            line = line[max_chars:]
        lines.append(line)

    chunks: list[str] = []
    current: list[str] = []
    for line in lines:
        if current and _joined_len(current) + 1 + len(line) > max_chars:
            chunks.append("\n".join(current).strip())
            current = _overlap_tail(current, overlap)
            if current and _joined_len(current) + 1 + len(line) > max_chars:
                current = []
        current.append(line)
    if current:
        chunks.append("\n".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def _joined_len(lines: list[str]) -> int:
    return sum(len(line) for line in lines) + max(0, len(lines) - 1)


def _overlap_tail(lines: list[str], overlap: int) -> list[str]:
    if overlap <= 0:
        return []
    tail: list[str] = []
    for line in reversed(lines):
        if _joined_len([line, *tail]) > overlap:
            break
        tail.insert(0, line)
    return tail
