"""Embedded Chroma vector store (optional ``vectors`` extra). Fail-safe everywhere."""
from __future__ import annotations

import functools

from .. import config
from . import db, embeddings


@functools.lru_cache(maxsize=1)
def _client():
    import chromadb
    return chromadb.PersistentClient(path=str(config.chroma_dir()))


def _collection():
    return _client().get_or_create_collection("memories")


def upsert_memory(memory_id: str) -> None:
    row = db.one("SELECT * FROM memories WHERE id=?", (memory_id,))
    if not row:
        return
    text = ((row.get("title") or "") + "\n" + (row.get("body") or "")).strip()
    vecs = embeddings.embed([text])
    if not vecs:
        return
    _collection().upsert(
        ids=[memory_id],
        embeddings=vecs,
        metadatas=[{"project_id": row["project_id"], "kind": row["kind"]}],
    )
    db.execute("UPDATE memories SET chroma_id=? WHERE id=?", (memory_id, memory_id))


def query_memories(project_id: str, query: str, k: int = 10) -> list[str]:
    vecs = embeddings.embed([query])
    if not vecs:
        return []
    res = _collection().query(
        query_embeddings=vecs, n_results=k, where={"project_id": project_id})
    ids = res.get("ids") or [[]]
    return list(ids[0])
