"""CLI: build (or rebuild) the retrieval index.

    python -m docmind.ingest
    python -m docmind.ingest --corpus ./my-docs --chunk-chars 1200
"""

from __future__ import annotations

import argparse
import json

from .config import settings
from .rag import RAGPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk, embed and index a markdown corpus")
    parser.add_argument("--corpus", default=None, help="directory of .md/.txt files")
    parser.add_argument("--chunk-chars", type=int, default=None)
    parser.add_argument("--overlap", type=int, default=None)
    parser.add_argument("--no-persist", action="store_true", help="build in memory only")
    args = parser.parse_args()

    if args.chunk_chars or args.overlap:
        # Settings is frozen; patch the module-level object used by the chunker.
        import docmind.config as config_module

        object.__setattr__(settings, "chunk_chars", args.chunk_chars or settings.chunk_chars)
        object.__setattr__(settings, "chunk_overlap", args.overlap or settings.chunk_overlap)
        _ = config_module  # keep the import meaningful for readers

    from pathlib import Path

    pipeline = RAGPipeline()
    result = pipeline.ingest(
        Path(args.corpus) if args.corpus else None, persist=not args.no_persist
    )
    print(json.dumps(result, indent=2))

    if not args.no_persist:
        print(f"\nIndex written to {settings.index_dir}")
        print("Try: python -m docmind.evaluate")


if __name__ == "__main__":
    main()
