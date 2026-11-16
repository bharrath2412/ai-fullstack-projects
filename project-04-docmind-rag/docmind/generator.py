"""Answer generation.

* `ExtractiveGenerator` — offline, deterministic, citation-first. It selects the
  sentences that actually answer the question from the retrieved chunks, so the
  demo never hallucinates and needs no API key.
* `OpenAIGenerator` — grounded prompt over the same contexts, with instructions
  to cite `[n]` and to refuse when the context is insufficient.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from .config import settings
from .embeddings import tokenize
from .store import RetrievedChunk

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`])")
_NOT_FOUND = (
    "I couldn't find a confident answer in the indexed documents. "
    "Try rephrasing the question, or ingest the document that covers it."
)


@dataclass
class Generation:
    """Answer text plus whether it is actually supported by the retrieved text."""

    text: str
    grounded: bool


class Generator(Protocol):
    name: str

    def generate(self, question: str, contexts: list[RetrievedChunk]) -> Generation:
        ...


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _body_without_heading(text: str, heading: str) -> str:
    """Chunks store their heading path at the top; don't quote that scaffolding."""
    if heading and text.startswith(heading):
        return text[len(heading) :].lstrip()
    return text


class ExtractiveGenerator:
    name = "extractive"

    def __init__(self, max_sentences: int = 4) -> None:
        self.max_sentences = max_sentences

    def generate(self, question: str, contexts: list[RetrievedChunk]) -> Generation:
        if not contexts:
            return Generation(_NOT_FOUND, grounded=False)

        query_terms = set(tokenize(question))
        if not query_terms:
            return Generation(_NOT_FOUND, grounded=False)

        # Refuse to answer when nothing in the retrieved context shares a term with
        # the question: better an honest "I don't know" than a confident non-answer.
        context_terms: set[str] = set()
        for context in contexts[:4]:
            context_terms |= set(tokenize(context.chunk.text))
        if not (query_terms & context_terms):
            closest = contexts[0]
            body = _clean(_body_without_heading(closest.chunk.text, closest.chunk.heading))
            return Generation(
                f"{_NOT_FOUND}\n\nClosest material: **{closest.chunk.title}** — {body[:240]}",
                grounded=False,
            )

        # Ignore weak retrievals: quoting an unrelated passage hurts precision more
        # than the extra sentence helps recall.
        top_score = contexts[0].score
        relevant = [
            context
            for context in contexts[:4]
            if context.score >= 0.75 * top_score
        ] or contexts[:1]

        scored: list[tuple[float, int, str]] = []
        for index, context in enumerate(relevant, start=1):
            body = _body_without_heading(context.chunk.text, context.chunk.heading)
            heading = context.chunk.heading.lower()
            for sentence in _SENTENCE_SPLIT.split(body):
                clean = _clean(sentence)
                if len(clean) < 30:
                    continue
                terms = tokenize(clean)
                if not terms:
                    continue
                overlap = len(query_terms & set(terms))
                if overlap == 0:
                    continue
                # normalise by length so long sentences don't always win
                score = overlap / (1 + len(terms) ** 0.5)
                if any(term in heading for term in query_terms):
                    score *= 1.25
                scored.append((score, index, clean))

        if not scored:
            top = contexts[0]
            body = _clean(_body_without_heading(top.chunk.text, top.chunk.heading))
            return Generation(
                f"{_NOT_FOUND}\n\nClosest material: **{top.chunk.title}** — {body[:240]}",
                grounded=False,
            )

        scored.sort(key=lambda row: row[0], reverse=True)
        chosen = scored[: self.max_sentences]
        chosen.sort(key=lambda row: (row[1], -row[0]))  # group by source order

        body = " ".join(f"{sentence} [{index}]" for _, index, sentence in chosen)
        used = sorted({index for _, index, _ in chosen})
        sources = "\n".join(f"[{index}] {relevant[index - 1].chunk.title}" for index in used)
        lead = relevant[used[0] - 1].chunk.title if used else ""
        prefix = f"**{lead}** — " if lead else ""
        return Generation(f"{prefix}{body}\n\n**Sources**\n{sources}", grounded=True)


class OpenAIGenerator:
    name = "openai"

    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.generator_model

    def _messages(self, question: str, contexts: list[RetrievedChunk]) -> list[dict]:
        blocks = [
            f"[{i}] {context.chunk.title}\n{context.chunk.text}"
            for i, context in enumerate(contexts, start=1)
        ]
        system = (
            "You are a documentation assistant. Answer ONLY from the numbered context blocks. "
            "Cite the blocks you use as [1], [2] inline. If the context does not contain the "
            "answer, say 'I don't know based on the provided documents' and stop. "
            "Be concise: at most 5 sentences."
        )
        return [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": "Context:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}",
            },
        ]

    def generate(self, question: str, contexts: list[RetrievedChunk]) -> Generation:
        response = httpx.post(
            f"{settings.openai_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": self.model,
                "messages": self._messages(question, contexts),
                "temperature": 0.1,
            },
            timeout=settings.request_timeout,
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"].strip().lower()
        refused = "i don't know" in text or "i do not know" in text
        return Generation(
            response.json()["choices"][0]["message"]["content"].strip(), grounded=not refused
        )


def get_generator(provider: str | None = None) -> Generator:
    provider = (provider or settings.generator_provider).lower()
    if provider == "extractive":
        return ExtractiveGenerator()
    if provider == "openai":
        return OpenAIGenerator()
    raise ValueError(f"Unknown generator provider {provider!r}")
