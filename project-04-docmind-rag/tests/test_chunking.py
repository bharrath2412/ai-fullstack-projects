"""Chunker tests: section boundaries, sizes, overlap, heading context."""

from __future__ import annotations

from pathlib import Path

import pytest

from docmind.chunking import Document, chunk_document, load_corpus, load_document


def make_document(text: str, name: str = "sample.md") -> Document:
    return Document(doc_id="sample", source=name, title="Sample", text=text)


def test_chunks_carry_heading_context():
    text = "# Pricing\n\nThe Team plan costs $24 per seat.\n\n## Enterprise\n\nSSO is Enterprise only.\n"
    chunks = chunk_document(make_document(text), chunk_chars=500, overlap=50, min_chars=10)
    assert len(chunks) == 2
    assert chunks[0].heading == "Pricing"
    assert chunks[0].text.startswith("Pricing")
    assert chunks[1].heading == "Pricing › Enterprise"
    assert "SSO" in chunks[1].text


def test_long_section_is_split_with_overlap():
    sentence = "This sentence exists purely to make the paragraph long enough to split. "
    text = "# Section\n\n" + sentence * 40
    chunks = chunk_document(make_document(text), chunk_chars=400, overlap=80, min_chars=50)
    assert len(chunks) > 3
    assert all(chunk.char_count <= 400 + 120 for chunk in chunks)  # heading prefix allowance
    positions = [chunk.position for chunk in chunks]
    assert positions == sorted(positions)
    assert len({chunk.id for chunk in chunks}) == len(chunks)


def test_short_fragments_are_dropped():
    text = "# A\n\nok\n\n## B\n\nThis section has enough content to be kept as a real chunk of text."
    chunks = chunk_document(make_document(text), chunk_chars=500, overlap=50, min_chars=40)
    assert all(len(chunk.text) >= 40 for chunk in chunks)


def test_tiny_sentence_splitting_falls_back_to_hard_cut():
    text = "# T\n\n" + ("x" * 1200)
    chunks = chunk_document(make_document(text), chunk_chars=300, overlap=20, min_chars=10)
    assert len(chunks) >= 3
    assert all(chunk.char_count < 400 for chunk in chunks)


def test_load_document_extracts_title_and_source(tmp_path: Path):
    path = tmp_path / "notes.md"
    path.write_text("# Real title\n\nBody text.", encoding="utf-8")
    document = load_document(path)
    assert document.title == "Real title"
    assert document.source == "notes.md"
    assert document.doc_id == "notes"


def test_corpus_is_discoverable():
    documents, chunks = load_corpus()
    assert len(documents) >= 4
    assert len(chunks) > 15
    sources = {document.source for document in documents}
    assert {"api-guide.md", "pricing.md", "runbook.md", "handbook.md"} <= sources
    # every chunk must reference an existing document
    assert {chunk.source for chunk in chunks} <= sources


def test_missing_corpus_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_corpus(tmp_path / "nope")


def test_empty_corpus_raises(tmp_path: Path):
    (tmp_path / "empty.md").write_text("# nothing\n\nok", encoding="utf-8")
    with pytest.raises(ValueError):
        load_corpus(tmp_path)
