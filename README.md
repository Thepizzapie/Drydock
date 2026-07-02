# Drydock

**Agents work in drydock, not on your ship.**

Local-first mission control for AI coding agents — isolated workspaces, hard policy
enforcement, and a full project-management system (tickets, memory, decisions, handoffs).
On your machine, one command, nothing leaves.

```
uvx drydock-ai
```

Status: pre-release (Phase 0 — storage + PM core). See [DESIGN.md](DESIGN.md).

## Honest by design

Isolation is tiered, and the active tier is always shown:

| Tier | Boundary | Requires |
|---|---|---|
| 0 | Policy-grade (aegis rules + confined tools). **Not a VM boundary.** | Nothing |
| 1 | WSL2 VM boundary, Windows drives unmounted | `wsl --install` (works on Windows Home) |
| 2 | Docker container | Docker |

License: Apache-2.0
