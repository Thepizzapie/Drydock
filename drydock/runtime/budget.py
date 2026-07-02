"""Per-run token / cost ceiling."""
from __future__ import annotations


class Budget:
    def __init__(self, spec: dict | None = None):
        spec = spec or {}
        self.max_tokens = spec.get("tokens")
        self.max_cost_usd = spec.get("cost_usd")
        self.tokens_in = 0
        self.tokens_out = 0

    def add(self, tin, tout):
        self.tokens_in += int(tin or 0)
        self.tokens_out += int(tout or 0)

    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    def exceeded(self) -> bool:
        if self.max_tokens and self.total_tokens() >= self.max_tokens:
            return True
        return False

    def totals(self) -> dict:
        return {"tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
                "total": self.total_tokens()}
