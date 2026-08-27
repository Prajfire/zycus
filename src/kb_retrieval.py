"""
kb_retrieval.py

Loads the markdown knowledge base, chunks it, and retrieves the most relevant
chunk(s) for a given ticket. No vector DB here on purpose — the corpus is ~10
files. A TF-IDF cosine search over heading-aware chunks gets us 90% of the
benefit of a real embedding index with none of the infra, and it's fully
deterministic (see design note in README for why that matters for Task 2).

If this were going into an actual product with a KB in the thousands of docs,
I'd swap this for a proper embedding store (see README "Scaling" section) —
the retrieve() interface below is written so that swap doesn't touch callers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

KB_ROOT = Path(__file__).resolve().parent.parent / "knowledge_base"


@dataclass
class Chunk:
    doc_path: str          # relative path, e.g. "products/databridge-pro.md"
    heading_trail: str      # "DataBridge Pro > Core Modules > Data Ingestion"
    text: str
    chunk_id: str


def _split_on_headings_and_rules(md_text: str) -> list[tuple[str, str]]:
    """
    Split a markdown doc into (heading_trail, body) chunks.
    Primary boundary: '---' horizontal rules (per DATA_SCHEMA.md's recommended
    chunking strategy). Secondary boundary: heading level, tracked so each
    chunk knows its place in the doc hierarchy.
    """
    lines = md_text.split("\n")
    heading_stack: list[str] = []
    chunks: list[tuple[str, str]] = []
    buffer: list[str] = []

    def flush():
        body = "\n".join(buffer).strip()
        if body:
            chunks.append((" > ".join(heading_stack), body))
        buffer.clear()

    for line in lines:
        if line.strip() == "---":
            flush()
            continue
        heading_match = re.match(r"^(#{1,4})\s+(.*)", line)
        if heading_match:
            flush()
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            heading_stack = heading_stack[: level - 1] + [title]
            continue
        buffer.append(line)
    flush()
    return chunks


def load_chunks() -> list[Chunk]:
    chunks: list[Chunk] = []
    for md_file in sorted(KB_ROOT.rglob("*.md")):
        rel = str(md_file.relative_to(KB_ROOT))
        text = md_file.read_text(encoding="utf-8")
        for i, (trail, body) in enumerate(_split_on_headings_and_rules(text)):
            # skip near-empty chunks (stray whitespace between rules)
            if len(body) < 40:
                continue
            chunks.append(
                Chunk(
                    doc_path=rel,
                    heading_trail=trail or Path(rel).stem,
                    text=body,
                    chunk_id=f"{rel}::{i}",
                )
            )
    return chunks


class KBIndex:
    """Small TF-IDF index over the KB chunks, built once and reused."""

    def __init__(self) -> None:
        self.chunks = load_chunks()
        corpus = [f"{c.heading_trail}\n{c.text}" for c in self.chunks]
        self.vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        self.matrix = self.vectorizer.fit_transform(corpus)

    def retrieve(self, query: str, top_k: int = 3) -> list[tuple[Chunk, float]]:
        if not query.strip():
            return []
        q_vec = self.vectorizer.transform([query])
        sims = cosine_similarity(q_vec, self.matrix)[0]
        ranked = sorted(range(len(sims)), key=lambda i: sims[i], reverse=True)
        return [(self.chunks[i], float(sims[i])) for i in ranked[:top_k] if sims[i] > 0]


_index: KBIndex | None = None


def get_index() -> KBIndex:
    """Module-level singleton so the FastAPI app / eval harness don't rebuild
    the TF-IDF matrix on every request."""
    global _index
    if _index is None:
        _index = KBIndex()
    return _index


if __name__ == "__main__":
    idx = get_index()
    print(f"Loaded {len(idx.chunks)} chunks from {KB_ROOT}")
    for chunk, score in idx.retrieve("ERR_CONNECTION_TIMEOUT after 30s ingestion pipeline"):
        print(f"{score:.3f}  {chunk.doc_path}  [{chunk.heading_trail}]")
