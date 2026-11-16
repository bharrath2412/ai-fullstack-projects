"""Embedder determinism + vector store correctness (including the alignment bug guard)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from docmind.chunking import Chunk
from docmind.embeddings import HashingEmbedder, get_embedder
from docmind.store import VectorStore


@pytest.fixture(scope="module")
def embedder():
    return HashingEmbedder(dim=256)


def test_embedding_is_deterministic(embedder):
    a = embedder.embed_one("How long do access tokens last?")
    b = embedder.embed_one("How long do access tokens last?")
    np.testing.assert_allclose(a, b)


def test_embedding_is_normalised(embedder):
    vector = embedder.embed_one("retrieval augmented generation")
    assert pytest.approx(float(np.linalg.norm(vector)), rel=1e-5) == 1.0


def test_embedding_shape_and_batch(embedder):
    batch = embedder.embed(["one", "two", "three"])
    assert batch.shape == (3, 256)
    empty = embedder.embed([])
    assert empty.shape == (0, 256)


def test_similar_text_scores_higher_than_unrelated(embedder):
    query = embedder.embed_one("how do I rotate an API key")
    related = embedder.embed_one("rotate a leaked API key immediately")
    unrelated = embedder.embed_one("the Team plan costs 24 dollars per seat")
    assert float(query @ related) > float(query @ unrelated)


def test_unknown_provider_raises():
    with pytest.raises(ValueError):
        get_embedder("telepathy")


def make_chunk(index: int, text: str) -> Chunk:
    return Chunk(
        id=f"c-{index}",
        doc_id="doc",
        source="doc.md",
        heading="Section",
        text=text,
        position=index,
        char_count=len(text),
    )


def test_score_all_is_aligned_with_chunk_order(embedder):
    texts = [
        "quarterly revenue recognition policy",
        "rotate a leaked api key within five seconds",
        "database failover promotes the synchronous replica",
    ]
    chunks = [make_chunk(i, text) for i, text in enumerate(texts)]
    store = VectorStore(dim=embedder.dim, embedding_name=embedder.name)
    store.add(chunks, embedder.embed(texts))

    scores = store.score_all(embedder.embed_one("rotate leaked api key"))
    assert scores.shape == (3,)
    assert int(np.argmax(scores)) == 1, "index 1 is the key-rotation chunk"

    top = store.search(embedder.embed_one("rotate leaked api key"), k=1)
    assert top[0][0].id == "c-1"
    assert top[0][0].id == chunks[int(np.argmax(scores))].id


def test_store_stats_and_sources(embedder):
    texts = ["alpha text about pricing", "beta text about runbooks"]
    store = VectorStore(dim=embedder.dim)
    store.add([make_chunk(0, texts[0]), make_chunk(1, texts[1])], embedder.embed(texts))
    stats = store.stats()
    assert stats["chunks"] == 2
    assert stats["dim"] == embedder.dim
    assert stats["per_document"] == {"doc.md": 2}


def test_store_save_and_load_roundtrip(embedder, tmp_path: Path):
    texts = ["one chunk about tokens", "another chunk about sso"]
    store = VectorStore(dim=embedder.dim, embedding_name=embedder.name)
    store.add([make_chunk(0, texts[0]), make_chunk(1, texts[1])], embedder.embed(texts))
    store.save(directory_override=tmp_path)

    reloaded = VectorStore.load(tmp_path)
    assert reloaded.dim == store.dim
    assert [c.id for c in reloaded.chunks] == [c.id for c in store.chunks]
    np.testing.assert_allclose(reloaded.matrix, store.matrix, rtol=1e-6)
    assert reloaded.embedding_name == embedder.name


def test_store_load_missing_index(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        VectorStore.load(tmp_path)


def test_store_rejects_dimension_mismatch(embedder):
    store = VectorStore(dim=8)
    with pytest.raises(ValueError):
        store.add([make_chunk(0, "text")], np.zeros((1, 4), dtype=np.float32))
