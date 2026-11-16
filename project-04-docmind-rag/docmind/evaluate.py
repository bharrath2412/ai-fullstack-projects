"""Offline retrieval/answer evaluation on a small golden set.

    python -m docmind.evaluate            # table of per-question results
    python -m docmind.evaluate --json     # machine-readable

Metrics: Hit@k (did the expected document appear in the top k?), MRR (mean
reciprocal rank of the first correct chunk) and answer keyword coverage (does the
generated answer contain the fact we expect?). This is the smallest useful
regression test for a RAG system.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any

from .rag import RAGPipeline

GOLDEN: list[dict[str, Any]] = [
    {
        "question": "How long does an API access token stay valid?",
        "expected_source": "api-guide.md",
        "expected_terms": ["60", "minute", "expire"],
    },
    {
        "question": "What should I do when I receive a 429 response?",
        "expected_source": "api-guide.md",
        "expected_terms": ["retry", "backoff", "429"],
    },
    {
        "question": "Which plans include single sign-on?",
        "expected_source": "pricing.md",
        "expected_terms": ["sso", "enterprise"],
    },
    {
        "question": "How much does the Team plan cost per seat?",
        "expected_source": "pricing.md",
        "expected_terms": ["24", "seat"],
    },
    {
        "question": "What is the on-call escalation path for a Sev-1 incident?",
        "expected_source": "runbook.md",
        "expected_terms": ["sev-1", "escalat", "on-call"],
    },
    {
        "question": "How do I rotate a leaked API key?",
        "expected_source": "runbook.md",
        "expected_terms": ["rotat", "key"],
    },
    {
        "question": "What chunk size does the ingestion pipeline use?",
        "expected_source": "handbook.md",
        "expected_terms": ["chunk", "900"],
    },
    {
        "question": "What is the data retention period for workspace exports?",
        "expected_source": "pricing.md",
        "expected_terms": ["export", "retention", "30"],
    },
    {
        "question": "Which endpoints support idempotency keys?",
        "expected_source": "api-guide.md",
        "expected_terms": ["idempotency", "post"],
    },
    {
        "question": "What happens during a database failover?",
        "expected_source": "runbook.md",
        "expected_terms": ["failover", "replica", "second"],
    },
]


@dataclass
class EvaluationReport:
    rows: list[dict[str, Any]] = field(default_factory=list)
    hit_at_k: float = 0.0
    mrr: float = 0.0
    keyword_coverage: float = 0.0
    k: int = 5

    def to_dict(self) -> dict[str, Any]:
        return {
            "k": self.k,
            "hit_at_k": round(self.hit_at_k, 4),
            "mrr": round(self.mrr, 4),
            "keyword_coverage": round(self.keyword_coverage, 4),
            "rows": self.rows,
        }


def evaluate(pipeline: RAGPipeline, golden: list[dict[str, Any]] | None = None, k: int = 5) -> EvaluationReport:
    cases = golden or GOLDEN
    report = EvaluationReport(k=k)
    reciprocal_ranks: list[float] = []
    coverage: list[float] = []

    for case in cases:
        result = pipeline.query(case["question"], top_k=k)
        sources = [citation.source for citation in result.citations]
        rank = next(
            (i + 1 for i, source in enumerate(sources) if source == case["expected_source"]), None
        )
        answer_lower = result.answer.lower()
        matched = [term for term in case["expected_terms"] if term.lower() in answer_lower]
        coverage_ratio = len(matched) / len(case["expected_terms"])

        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
        coverage.append(coverage_ratio)
        report.rows.append(
            {
                "question": case["question"],
                "expected_source": case["expected_source"],
                "top_sources": sources[:3],
                "rank": rank,
                "hit": rank is not None,
                "terms_matched": matched,
                "keyword_coverage": round(coverage_ratio, 3),
                "answer": result.answer[:180],
                "timings": result.timings,
            }
        )

    report.hit_at_k = sum(1 for row in report.rows if row["hit"]) / len(report.rows)
    report.mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)
    report.keyword_coverage = sum(coverage) / len(coverage)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval + answers on the golden set")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    pipeline = RAGPipeline.from_disk()
    report = evaluate(pipeline, k=args.k)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return

    print(f"Retrieval evaluation · k={report.k} · {len(report.rows)} questions\n")
    for row in report.rows:
        mark = "PASS" if row["hit"] else "MISS"
        print(f"[{mark}] rank={row['rank']} cov={row['keyword_coverage']:.2f}  {row['question']}")
        print(f"        expected={row['expected_source']} got={row['top_sources']}")
        if args.verbose or not row["hit"]:
            print(f"        answer: {row['answer']}")
    print(
        f"\nHit@{report.k}: {report.hit_at_k:.1%} | MRR: {report.mrr:.3f} | "
        f"Keyword coverage: {report.keyword_coverage:.1%}"
    )

    # Non-zero exit keeps this usable as a CI gate.
    if report.hit_at_k < 0.7 or report.mrr < 0.5:
        print("\nFAIL: retrieval quality below the gate (hit@k >= 0.70, mrr >= 0.50)", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
