"""Markdown-aware, header-preserving chunker.

Naive fixed-size splitting destroys the context a retrieval model needs (a chunk
that starts mid-sentence, with no idea which document or section it came from).
This chunker:

* splits on markdown headings and keeps the heading path as metadata
* packs paragraphs up to a character budget without breaking sentences
* adds an overlap tail so answers spanning a boundary remain retrievable
* prefixes each chunk with its heading path, which materially improves retrieval
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import settings

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Chunk:
    id: str
    doc_id: str
    source: str
    heading: str
    text: str
    position: int
    char_count: int
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "doc_id": self.doc_id,
            "source": self.source,
            "heading": self.heading,
            "text": self.text,
            "position": self.position,
            "char_count": self.char_count,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Chunk":
        return cls(**data)

    @property
    def title(self) -> str:
        return f"{self.source} › {self.heading}" if self.heading else self.source


@dataclass
class Document:
    doc_id: str
    source: str
    title: str
    text: str
    chunks: list[Chunk] = field(default_factory=list)


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "section"


def _split_long_text(text: str, limit: int, overlap: int) -> list[str]:
    """Split on sentence boundaries, fall back to hard cuts for very long sentences."""
    if len(text) <= limit:
        return [text]
    sentences = _SENTENCE_END.split(text)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        if len(sentence) > limit:  # pathological sentence
            if current:
                pieces.append(current)
                current = ""
            for i in range(0, len(sentence), limit):
                pieces.append(sentence[i : i + limit])
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= limit:
            current = candidate
        else:
            pieces.append(current)
            tail = current[-overlap:] if overlap and current else ""
            current = f"{tail} {sentence}".strip()
    if current:
        pieces.append(current)
    return [p for p in pieces if p.strip()]


def load_document(path: Path) -> Document:
    text = path.read_text(encoding="utf-8", errors="replace")
    title = path.stem
    first_heading = next(
        (m.group(2).strip() for m in (_HEADING.match(line) for line in text.splitlines()) if m), None
    )
    if first_heading:
        title = first_heading
    return Document(
        doc_id=_slugify(path.stem),
        source=path.name,
        title=title,
        text=text,
    )


def chunk_document(
    document: Document,
    *,
    chunk_chars: int | None = None,
    overlap: int | None = None,
    min_chars: int | None = None,
) -> list[Chunk]:
    limit = chunk_chars or settings.chunk_chars
    tail = overlap if overlap is not None else settings.chunk_overlap
    minimum = min_chars if min_chars is not None else settings.min_chunk_chars

    lines = document.text.splitlines()
    sections: list[tuple[str, list[str]]] = []
    heading_path: list[str] = []
    current_heading = document.title
    buffer: list[str] = []

    for line in lines:
        match = _HEADING.match(line)
        if match:
            depth = len(match.group(1))
            name = match.group(2).strip()
            if buffer:
                sections.append((current_heading, buffer))
                buffer = []
            heading_path = heading_path[: depth - 1] + [name]
            current_heading = " › ".join(heading_path) or name
        else:
            buffer.append(line)
    if buffer:
        sections.append((current_heading, buffer))

    chunks: list[Chunk] = []
    position = 0
    for heading, section_lines in sections:
        body = "\n".join(section_lines).strip()
        body = re.sub(r"\n{3,}", "\n\n", body)
        if not body:
            continue
        for piece in _split_long_text(body, limit, tail):
            if len(piece.strip()) < minimum:
                continue
            # Heading prefix keeps section context inside the embedded text.
            prefixed = f"{heading}\n\n{piece.strip()}" if heading else piece.strip()
            chunks.append(
                Chunk(
                    id=f"{document.doc_id}-{position:03d}",
                    doc_id=document.doc_id,
                    source=document.source,
                    heading=heading,
                    text=prefixed,
                    position=position,
                    char_count=len(prefixed),
                )
            )
            position += 1
    return chunks


def load_corpus(corpus_dir: Path | None = None) -> tuple[list[Document], list[Chunk]]:
    """Read every .md/.txt file in the corpus directory and chunk it."""
    directory = Path(corpus_dir or settings.corpus_dir)
    if not directory.exists():
        raise FileNotFoundError(f"Corpus directory not found: {directory}")

    documents: list[Document] = []
    all_chunks: list[Chunk] = []
    for path in sorted([*directory.glob("*.md"), *directory.glob("*.txt")]):
        document = load_document(path)
        document.chunks = chunk_document(document)
        documents.append(document)
        all_chunks.extend(document.chunks)
    if not all_chunks:
        raise ValueError(f"No chunkable documents found in {directory}")
    return documents, all_chunks
