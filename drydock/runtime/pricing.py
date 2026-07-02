"""Model pricing — cost per run, honestly.

Cents per 1k tokens (input, output), longest-prefix match on the model id.
Anything that doesn't match a known cloud model is treated as local: cost 0,
flagged is_local so the UI can say "local · $0.00" instead of pretending.
"""
from __future__ import annotations

# cents per 1k tokens: (input, output)
_PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5": (0.50, 2.50),
    "claude-opus-4": (1.50, 7.50),
    "claude-sonnet-5": (0.30, 1.50),
    "claude-sonnet-4": (0.30, 1.50),
    "claude-haiku-4": (0.10, 0.50),
    "gpt-5": (0.125, 1.00),
    "gpt-4o": (0.25, 1.00),
}


def rates(model: str | None) -> tuple[float, float] | None:
    """(in, out) cents/1k for a known cloud model, else None."""
    if not model:
        return None
    m = model.lower()
    best = None
    for prefix, r in _PRICES.items():
        if m.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), r)
    return best[1] if best else None


def is_local(model: str | None) -> bool:
    return rates(model) is None


def cost_cents(model: str | None, tokens_in: int, tokens_out: int) -> int:
    r = rates(model)
    if not r:
        return 0
    return round((tokens_in or 0) / 1000 * r[0] + (tokens_out or 0) / 1000 * r[1])
