from dataclasses import dataclass

_SEPARATORS = ["\n\n", "\n", ". ", "۔ ", "؟ ", "! ", "? ", " "]


@dataclass(frozen=True)
class Block:
    """A parsed piece of a document with its structural metadata."""

    text: str
    page: int | None = None
    heading: str | None = None


@dataclass(frozen=True)
class Chunk:
    text: str
    index: int
    page: int | None = None
    heading: str | None = None


def _split_oversized(text: str, size: int, separators: list[str]) -> list[str]:
    if len(text) <= size:
        return [text]
    if not separators:
        return [text[i : i + size] for i in range(0, len(text), size)]
    sep, rest = separators[0], separators[1:]
    if sep not in text:
        return _split_oversized(text, size, rest)
    parts = text.split(sep)
    pieces: list[str] = []
    current = ""
    for part in parts:
        candidate = f"{current}{sep}{part}" if current else part
        if len(candidate) <= size:
            current = candidate
            continue
        if current:
            pieces.append(current)
        if len(part) <= size:
            current = part
        else:
            pieces.extend(_split_oversized(part, size, rest))
            current = ""
    if current:
        pieces.append(current)
    return pieces


def _overlap_tail(text: str, overlap: int) -> str:
    if overlap <= 0 or len(text) <= overlap:
        return text if overlap > 0 else ""
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1 :] if space != -1 else tail


def chunk_blocks(blocks: list[Block], size: int, overlap: int) -> list[Chunk]:
    """Split blocks into <=size chunks, keeping page/heading metadata and word-boundary overlap.

    Overlap is carried between chunks of the same block only, so a chunk never
    mixes two pages or two sections.
    """
    chunks: list[Chunk] = []
    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        pieces = _split_oversized(text, size, _SEPARATORS)
        carry = ""
        for piece in pieces:
            body = f"{carry} {piece}".strip() if carry else piece
            chunks.append(
                Chunk(text=body, index=len(chunks), page=block.page, heading=block.heading)
            )
            carry = _overlap_tail(piece, overlap)
    return chunks