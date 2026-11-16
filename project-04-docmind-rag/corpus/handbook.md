# Engineering handbook

How the retrieval pipeline is built, how we evaluate it, and the conventions every service in
the repository follows.

## Architecture in one page

```
documents ──► chunker ──► embedder ──► vector store
                                             │
question ──► query embedder ──► hybrid retrieval (dense + BM25 + MMR)
                                             │
                                       prompt builder ──► generator ──► answer + citations
```

The pipeline is deliberately boring: an index, a retriever, a prompt, a generator. Every stage
is replaceable on its own, and every stage reports its own timing.

## Chunking policy

Chunks are markdown-section aware. The ingestion pipeline uses a **chunk size of 900
characters** with a **150 character overlap**, and drops fragments shorter than 80 characters.
Each chunk is prefixed with its heading path (for example `Engineering handbook › Chunking
policy`) so the embedding carries section context even when the body is a fragment.

Rules of thumb we validated against our golden set:

- 900/150 beat both 500/50 (too fragmented, citations became useless) and 1600/200 (answers
  pulled in unrelated paragraphs).
- Overlap matters most at section boundaries; without it, answers that span two paragraphs are
  unretrievable roughly 12% of the time.
- Never split tables or code blocks: they lose their meaning when separated from the header row.

## Embeddings

Default production embeddings come from a hosted model (1536 dimensions, cosine similarity,
normalised at write time). The repository's offline fallback is a 384-dimensional hashing
embedder built from word unigrams, bigrams and character trigrams with sublinear term
frequency and L2 normalisation. It is deterministic and good at exact identifiers, which is why
it is fused with BM25 rather than replacing it.

## Hybrid retrieval

Dense and keyword scores are normalised to [0, 1], then combined 55/45 (dense/keyword) by
default. Maximal marginal relevance with λ=0.65 removes near-duplicate chunks from the top-k.
Retrieval returns the top 5 chunks unless the caller asks for more; beyond 8, precision drops
and prompt cost rises faster than answer quality.

## Evaluation

`python -m docmind.evaluate` runs ten golden questions and reports Hit@5, MRR and keyword
coverage. The CI gate fails the build below Hit@5 = 0.70 or MRR = 0.50. When you change the
chunker, embedder or fusion weights, run the evaluation before and after — improvements that
are invisible on the golden set are usually invisible to users too.

## Code conventions

- Python 3.11+, type hints on every public function, `from __future__ import annotations`.
- Dataclasses for internal data, pydantic models at the HTTP boundary.
- No global mutable state outside a single lazily-initialised pipeline object.
- Tests must run offline: no network, no API keys, deterministic seeds.
- Every service exposes `/health`; every error response carries a stable machine-readable code.

## Local development

```bash
pip install -r requirements-dev.txt
python -m docmind.ingest          # build ./data/index
uvicorn docmind.service:app --reload --port 8200
python -m pytest                  # offline tests
```

## Incident learning

Post-incident reviews are blameless and timeboxed to 48 hours. The output is a short document
with a timeline, contributing factors and action items. We track the percentage of action items
closed within 30 days as a team health metric — currently 84%.
