"""Budget-aware context assembly — near-verbatim port of orbit ``allocator.py``.

Scoring: score = importance * recency_decay * relevance
  - importance: memory column, or a fixed prior per type (_PRIOR)
  - recency_decay = 0.5 ** (age_days / 14)  (half-life two weeks)
  - relevance: 1.0 unless the item came from query search, where rank 0 -> 1.0
    falling off as 1/(1+position)

Knapsack: pinned memories always ship first (no budget competition); the rest
sort by density (score / token_cost, ~4 chars/token) and pack greedily.
"""
from __future__ import annotations

import datetime

from . import db, service

HALFLIFE = 14.0

_PRIOR = {
    "handoff": 0.9,
    "decision": 0.75,
    "work_item": 0.6,
}

_UTC = datetime.timezone.utc


def _now():
    return datetime.datetime.now(_UTC)


def _to_dt(v):
    if v is None:
        return None
    if isinstance(v, datetime.datetime):
        return v if v.tzinfo else v.replace(tzinfo=_UTC)
    if isinstance(v, str):
        try:
            d = datetime.datetime.fromisoformat(v)
            return d if d.tzinfo else d.replace(tzinfo=_UTC)
        except ValueError:
            return None
    return None


def _age_days(*candidates):
    best = None
    for c in candidates:
        d = _to_dt(c)
        if d and (best is None or d > best):
            best = d
    if best is None:
        return 0.0
    return max(0.0, (_now() - best).total_seconds() / 86400.0)


def _recency_decay(age_days: float) -> float:
    return 0.5 ** (age_days / HALFLIFE)


def _tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


def _item(type_, id_, title, text, score, tokens):
    return {
        "type": type_,
        "id": str(id_) if id_ is not None else None,
        "title": title,
        "text": text,
        "score": round(float(score), 5),
        "tokens": int(tokens),
    }


def _handoff_text(h: dict) -> str:
    parts = []
    if h.get("summary"):
        parts.append(h["summary"])
    if h.get("current_state"):
        parts.append(f"State: {h['current_state']}")
    steps = [s.get("text", s) if isinstance(s, dict) else s
             for s in (h.get("next_steps") or [])]
    if steps:
        parts.append("Next: " + "; ".join(str(s) for s in steps))
    blockers = [b.get("text", b) if isinstance(b, dict) else b
                for b in (h.get("blockers") or [])]
    if blockers:
        parts.append("Blockers: " + "; ".join(str(b) for b in blockers))
    return "\n".join(parts) or "(handoff)"


def assemble(project, token_budget: int = 2000, query: str | None = None) -> dict:
    """Budget-bounded context packet: {"items", "total_tokens", "budget", "dropped"}."""
    pid = service._pid(project)
    ts_now = db.now()
    pinned_items: list[dict] = []
    scored: list[dict] = []
    seen_mem: set[str] = set()

    # --- pinned memories: always included, taken first ---
    for r in db.q(
        """SELECT id, title, body, importance, last_accessed, created_at
           FROM memories
           WHERE project_id=? AND pinned=1
             AND (valid_to IS NULL OR valid_to > ?)
           ORDER BY importance DESC, created_at DESC
           LIMIT 20""",
        (pid, ts_now),
    ):
        mid = str(r["id"])
        seen_mem.add(mid)
        text = ((r["title"] + "\n") if r.get("title") else "") + (r["body"] or "")
        decay = _recency_decay(_age_days(r.get("last_accessed"), r.get("created_at")))
        score = float(r.get("importance") or 0.5) * decay * 1.0
        pinned_items.append(_item("memory", mid, r.get("title"), text, score, _tokens(text)))

    # --- active handoff ---
    handoff = service.get_handoff(project)
    if handoff:
        text = _handoff_text(handoff)
        decay = _recency_decay(_age_days(handoff.get("updated_at"), handoff.get("created_at")))
        score = _PRIOR["handoff"] * decay * 1.0
        scored.append(_item("handoff", handoff.get("id"), "Active handoff", text, score, _tokens(text)))

    # --- active decisions ---
    for d in db.q(
        """SELECT id, title, rationale, created_at FROM decisions
           WHERE project_id=? AND status='active'
           ORDER BY created_at DESC LIMIT 15""",
        (pid,),
    ):
        text = (d["title"] or "") + (("\n" + d["rationale"]) if d.get("rationale") else "")
        decay = _recency_decay(_age_days(d.get("created_at")))
        score = _PRIOR["decision"] * decay * 1.0
        scored.append(_item("decision", d["id"], d.get("title"), text, score, _tokens(text)))

    # --- open work items ---
    for w in db.q(
        """SELECT id, type, title, body, status, priority, updated_at FROM work_items
           WHERE project_id=? AND status IN ('open','in_progress','blocked')
           ORDER BY priority, updated_at DESC LIMIT 25""",
        (pid,),
    ):
        text = f"[{w['status']}] {w['title']}" + (("\n" + w["body"]) if w.get("body") else "")
        decay = _recency_decay(_age_days(w.get("updated_at")))
        prio_boost = 1.0 + max(0, 3 - int(w.get("priority") or 3)) * 0.1
        score = _PRIOR["work_item"] * prio_boost * decay * 1.0
        scored.append(_item("work_item", w["id"], w.get("title"), text, score, _tokens(text)))

    # --- semantic / recent memories ---
    if query:
        hits = service.search_context(project, query, k=12)
        for pos, m in enumerate(hits):
            mid = str(m["id"])
            if mid in seen_mem:
                continue
            seen_mem.add(mid)
            text = ((m["title"] + "\n") if m.get("title") else "") + (m["body"] or "")
            decay = _recency_decay(_age_days(m.get("last_accessed"), m.get("created_at")))
            relevance = 1.0 / (1.0 + pos)
            score = float(m.get("importance") or 0.5) * decay * relevance
            scored.append(_item("memory", mid, m.get("title"), text, score, _tokens(text)))
    else:
        for r in db.q(
            """SELECT id, title, body, importance, last_accessed, created_at
               FROM memories
               WHERE project_id=? AND pinned=0
                 AND tier <> 'cold'
                 AND (valid_to IS NULL OR valid_to > ?)
               ORDER BY importance DESC,
                        COALESCE(last_accessed, '') DESC,
                        created_at DESC
               LIMIT 30""",
            (pid, ts_now),
        ):
            mid = str(r["id"])
            if mid in seen_mem:
                continue
            seen_mem.add(mid)
            text = ((r["title"] + "\n") if r.get("title") else "") + (r["body"] or "")
            decay = _recency_decay(_age_days(r.get("last_accessed"), r.get("created_at")))
            score = float(r.get("importance") or 0.5) * decay * 1.0
            scored.append(_item("memory", mid, r.get("title"), text, score, _tokens(text)))

    # --- greedy knapsack: pinned first, then densest-first until budget hit ---
    for it in pinned_items:
        it["_pinned"] = True
    selected = list(pinned_items)
    total = sum(it["tokens"] for it in selected)
    dropped = 0

    scored.sort(key=lambda it: it["score"] / it["tokens"], reverse=True)
    for it in scored:
        if total + it["tokens"] <= token_budget:
            selected.append(it)
            total += it["tokens"]
        else:
            dropped += 1

    selected.sort(key=lambda it: (not it.get("_pinned"), -it["score"]))
    for it in selected:
        it.pop("_pinned", None)

    return {
        "items": selected,
        "total_tokens": total,
        "budget": token_budget,
        "dropped": dropped,
    }


_TYPE_LABEL = {
    "memory": "Memory",
    "handoff": "Handoff",
    "decision": "Decision",
    "work_item": "Work item",
}


def render(assembled: dict) -> str:
    """Render an assembled packet as compact markdown ready for prompt injection."""
    items = assembled.get("items", [])
    lines = [
        f"# Context ({assembled.get('total_tokens', 0)}/{assembled.get('budget', 0)} tokens"
        f", {len(items)} items, {assembled.get('dropped', 0)} dropped)",
        "",
    ]
    for it in items:
        label = _TYPE_LABEL.get(it["type"], it["type"])
        title = it.get("title") or "(untitled)"
        lines.append(f"## {label}: {title}  ·  score={it['score']} · ~{it['tokens']}t")
        body = (it.get("text") or "").strip()
        lines.append(body)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
