"""Local knowledge-base search (BM25 over markdown chunks).

A dependency-free retrieval tool so the agent can answer questions about its
own architecture without any external vector database.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from ...config import BASE_DIR
from .base import Tool, ToolError

KNOWLEDGE_DIR = BASE_DIR / "app" / "data" / "knowledge"
_TOKEN = re.compile(r"[a-z0-9_]+")
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "it", "for", "on", "with",
    "how", "does", "do", "what", "why", "can", "i", "you", "my", "this", "that", "are",
    "be", "as", "at", "by", "from", "we", "our", "use", "used", "using", "which",
}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


def _chunk(text: str, heading: str = "") -> list[tuple[str, str]]:
    """Split markdown into heading-delimited chunks."""
    chunks: list[tuple[str, str]] = []
    current_title = heading or "Overview"
    buffer: list[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            if buffer:
                chunks.append((current_title, "\n".join(buffer).strip()))
                buffer = []
            current_title = line.lstrip("#").strip() or current_title
        else:
            buffer.append(line)
    if buffer:
        chunks.append((current_title, "\n".join(buffer).strip()))
    return [(title, body) for title, body in chunks if body]


class KnowledgeBase:
    def __init__(self, directory: Path = KNOWLEDGE_DIR) -> None:
        self.directory = directory
        self.chunks: list[dict] = []
        self._df: Counter = Counter()
        self._avg_len = 0.0
        self.load()

    def load(self) -> None:
        self.chunks = []
        self._df = Counter()
        if not self.directory.exists():
            return
        for path in sorted(self.directory.glob("**/*.md")):
            source = path.name
            for title, body in _chunk(path.read_text(encoding="utf-8"), path.stem):
                tokens = tokenize(body)
                # Headings are strong signals — weight them 3x in the bag of words.
                title_tokens = tokenize(title)
                for token in title_tokens:
                    tokens.extend([token, token, token])
                self.chunks.append(
                    {
                        "source": source,
                        "title": title,
                        "text": body,
                        "tokens": Counter(tokens),
                        "length": max(len(tokens), 1),
                    }
                )
                for term in set(tokens):
                    self._df[term] += 1
        if self.chunks:
            self._avg_len = sum(c["length"] for c in self.chunks) / len(self.chunks)

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        terms = tokenize(query)
        if not terms or not self.chunks:
            return []
        n = len(self.chunks)
        k1, b = 1.5, 0.75
        scored = []
        for chunk in self.chunks:
            score = 0.0
            for term in terms:
                tf = chunk["tokens"].get(term, 0)
                if not tf:
                    continue
                df = self._df.get(term, 0) or 1
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                denom = tf + k1 * (1 - b + b * chunk["length"] / self._avg_len)
                score += idf * (tf * (k1 + 1)) / denom
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [{**chunk, "score": round(score, 3)} for score, chunk in scored[:top_k]]


_kb: KnowledgeBase | None = None


def knowledge_base() -> KnowledgeBase:
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb


async def doc_search(query: str, top_k: int = 3) -> str:
    results = knowledge_base().search(query, top_k=top_k)
    if not results:
        raise ToolError("No documentation matched that query")
    blocks = []
    for i, hit in enumerate(results, start=1):
        blocks.append(
            f"[{i}] {hit['source']} › {hit['title']} (score {hit['score']})\n{hit['text']}"
        )
    return "\n\n".join(blocks)


doc_search_tool = Tool(
    name="doc_search",
    description=(
        "Search the internal knowledge base (product docs, architecture notes and runbooks) "
        "for passages relevant to the question. Returns the best matching sections with sources."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural-language search query"},
            "top_k": {"type": "integer", "description": "Number of passages (default 3)"},
        },
        "required": ["query"],
    },
    func=doc_search,
    max_output_chars=5000,
)
