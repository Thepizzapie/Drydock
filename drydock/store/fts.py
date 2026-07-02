"""Recall: FTS5 lexical search, optional vector leg, RRF fusion.

Tiers (auto-detected, never required):
  1. FTS5 (always available — stdlib sqlite3)
  2. + ChromaDB embedded vectors when the ``vectors`` extra is installed AND an
     embedding backend exists (Ollama autodetect or the ``embeddings`` extra).

``search_memories`` is the single entry point; when both legs run, results are
fused with Reciprocal Rank Fusion (orbit's ranking).
"""
from __future__ import annotations

import re

from . import db
from .db import load_row, now

_RRF_K = 60  # standard RRF constant


# ── fts query sanitation ────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}")


def _fts_query(text: str) -> str | None:
    """Turn arbitrary text into a safe FTS5 OR-query. None if no usable tokens."""
    tokens = _TOKEN_RE.findall(text or "")[:12]
    if not tokens:
        return None
    return " OR ".join(f'"{t}"' for t in tokens)


# ── lexical leg ─────────────────────────────────────────────────────────────

def _fts_memories(pid: str, query: str, k: int) -> list[dict]:
    match = _fts_query(query)
    if not match:
        return []
    return db.q(
        """SELECT m.*, bm25(memories_fts) AS _rank
           FROM memories_fts f
           JOIN memories m ON m.rowid = f.rowid
           WHERE memories_fts MATCH ?
             AND m.project_id = ?
             AND (m.valid_to IS NULL OR m.valid_to > ?)
           ORDER BY _rank
           LIMIT ?""",
        (match, pid, now(), k),
    )


# ── vector leg (optional, fail-safe) ────────────────────────────────────────

def _vector_available() -> bool:
    try:
        import chromadb  # noqa: F401
        from . import embeddings
        return embeddings.available()
    except ImportError:
        return False


def _vector_memories(pid: str, query: str, k: int) -> list[dict]:
    try:
        from . import chroma
        ids = chroma.query_memories(pid, query, k=k)
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        rows = db.q(f"SELECT * FROM memories WHERE id IN ({marks})", ids)
        by_id = {r["id"]: r for r in rows}
        return [by_id[i] for i in ids if i in by_id]
    except Exception:
        return []  # the vector leg must never break recall


def embed_memory(memory_id: str) -> None:
    """Best-effort embed of one memory (no-op without the vectors extra)."""
    if not _vector_available():
        return
    try:
        from . import chroma
        chroma.upsert_memory(memory_id)
    except Exception:
        pass


# ── fusion + entry point ────────────────────────────────────────────────────

def _rrf(ranked_lists: list[list[dict]], k: int) -> list[dict]:
    scores: dict[str, float] = {}
    rows: dict[str, dict] = {}
    for lst in ranked_lists:
        for pos, r in enumerate(lst):
            rid = r["id"]
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (_RRF_K + pos + 1)
            rows.setdefault(rid, r)
    ordered = sorted(scores, key=scores.get, reverse=True)[:k]
    return [rows[i] for i in ordered]


def search_memories(project, query, k=5, kind=None, tags=None) -> list[dict]:
    from . import service
    pid = service._pid(project)

    if query:
        legs = [_fts_memories(pid, query, k * 2)]
        if _vector_available():
            legs.append(_vector_memories(pid, query, k * 2))
        hits = _rrf(legs, k) if len(legs) > 1 else legs[0][:k]
    else:
        hits = db.q(
            """SELECT * FROM memories
               WHERE project_id=? AND (valid_to IS NULL OR valid_to > ?)
               ORDER BY pinned DESC, importance DESC, created_at DESC
               LIMIT ?""",
            (pid, now(), k),
        )

    if kind:
        hits = [h for h in hits if h.get("kind") == kind]
    if tags:
        want = set(tags)
        hits = [h for h in hits
                if want & set(db.loads(h.get("tags_json"), default=[]))]

    # touch last_accessed (recall = access; feeds recency decay)
    ids = [h["id"] for h in hits]
    if ids:
        marks = ",".join("?" for _ in ids)
        db.execute(f"UPDATE memories SET last_accessed=? WHERE id IN ({marks})",
                   [now(), *ids])

    out = []
    for h in hits:
        h.pop("_rank", None)
        out.append(load_row(dict(h), ("tags",)))
    return out


def search_tickets(project, query, k=10) -> list[dict]:
    from . import service
    pid = service._pid(project)
    match = _fts_query(query)
    if not match:
        return []
    return db.q(
        """SELECT t.*, bm25(tickets_fts) AS _rank
           FROM tickets_fts f
           JOIN tickets t ON t.rowid = f.rowid
           WHERE tickets_fts MATCH ? AND t.project_id=?
           ORDER BY _rank LIMIT ?""",
        (match, pid, k),
    )
