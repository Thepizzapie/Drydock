"""Graph write helpers — port of orbit ``graph_links.py`` (file entities + edges)."""
from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

from . import db
from .db import now, ulid


def _norm(path: str, root: str | None = None) -> str:
    """Normalize a path to forward slashes, relative to the project root when possible."""
    p = str(path).replace("\\", "/").strip()
    if root:
        r = str(root).replace("\\", "/").rstrip("/")
        if p.lower().startswith(r.lower() + "/"):
            p = p[len(r) + 1:]
    # collapse ./ and ../ conservatively without touching the filesystem
    parts = []
    for seg in p.split("/"):
        if seg in ("", "."):
            continue
        if seg == ".." and parts:
            parts.pop()
        else:
            parts.append(seg)
    return "/".join(parts)


def ensure_entity(pid: str, kind: str, name: str, meta: dict | None = None) -> str:
    row = db.one(
        "SELECT id FROM entities WHERE project_id=? AND kind=? AND name=?",
        (pid, kind, name))
    if row:
        return row["id"]
    eid = ulid()
    db.execute(
        "INSERT INTO entities(id, project_id, kind, name, meta_json, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (eid, pid, kind, name, db.dumps(meta or {}), now()))
    return eid


def ensure_file_entity(pid: str, path: str) -> str | None:
    if not path:
        return None
    return ensure_entity(pid, "file", path)


def _add_edge(pid: str, src_type: str, src_id: str, dst_type: str, dst_id: str,
              relation: str, weight: float = 1.0) -> bool:
    """Insert a live edge if absent. Returns True when a new edge was created."""
    existing = db.one(
        """SELECT id FROM relationships
           WHERE project_id=? AND src_type=? AND src_id=? AND dst_type=? AND dst_id=?
             AND relation=? AND valid_to IS NULL""",
        (pid, src_type, src_id, dst_type, dst_id, relation))
    if existing:
        return False
    db.execute(
        """INSERT INTO relationships(id, project_id, src_type, src_id, dst_type, dst_id,
                                     relation, weight, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (ulid(), pid, src_type, src_id, dst_type, dst_id, relation, weight, now()))
    return True
