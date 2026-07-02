# Drydock — Design (locked 2026-07-02)

**Agents work in drydock, not on your ship.** Local-first platform where AI coding agents get
isolated workspaces, hard policy enforcement, and a full project-management system — tickets,
memory, decisions, handoffs — with a mission-control dashboard.

**Drydock is orbit's PM system + Aegis's policy kernel + a native agent runtime.**
It is NOT just an agent studio. The PM plane (work, memory, context) is a first-class half of
the product; the runtime is one module inside it.

Sources:
- Control plane: port of `orbit-public` (C:\Users\adria\Desktop\orbit-public) — Postgres→SQLite
- Policy kernel: `aegis-hooks` (C:\Users\adria\Desktop\AEGIS) — imported as a library, not forked
- Runtime: greenfield, OpenCode used as blueprint only (headless server, agents-as-markdown with
  default-deny permissions, provider layer, event streams)

Distribution: PyPI package **`drydock-ai`**, CLI command **`drydock`**, install `uvx drydock-ai`.
OSS core (Apache-2.0); Pro tier later (signed installer, container fleets, compliance exports).

---

## 1. Locked decisions

| # | Decision | Why |
|---|---|---|
| D1 | Python 3.11+, single package | Both parents are Python; aegis imports in-process |
| D2 | SQLite (WAL) + FTS5, one DB file | Kills the Postgres/Docker install requirement — the seamless-install decision |
| D3 | ChromaDB embedded as optional extra; embeddings tiered: none (FTS-only) → Ollama autodetect → `[embeddings]` extra (fastembed ONNX) | Zero required services |
| D4 | `aegis-hooks` as dependency; audit unified into SQLite (`audit` table), JSONL mirror optional | One audit story for native runs AND external hook events |
| D5 | Worker-in-sandbox architecture: policy kernel on host (trusted), tool executor inside sandbox (untrusted), JSON-RPC over stdio | The kernel must be unreachable from sandboxed code |
| D6 | Sandbox tiers: 0 = policy-only confinement (zero deps) · 1 = WSL2 dedicated distro, drives unmounted (recommended on Windows) · 2 = Docker (cross-platform) | Honest, layered; Tier 1 = hard isolation without Docker Desktop, works on Win11 Home |
| D7 | Agents = markdown files with YAML frontmatter; anything not declared is denied; frontmatter compiles to aegis rules | OpenCode's best idea, enforced by our kernel |
| D8 | Providers: Anthropic first + one OpenAI-compatible client (covers Ollama/local) | No provider matrix in v1 |
| D9 | orbit's MCP tool surface preserved (renamed) + new run/ask tools | Claude Code can use Drydock as its PM even without the runtime |
| D10 | UI: hand-crafted static app (vanilla ES modules + CSS tokens, no framework, no build step) shipped in the wheel at `drydock/_data/ui/`, served by FastAPI. No Node for users OR for the build | Matches the owner's taste (hand-crafted over generated framework code) and makes local-first trivially true — zero network, zero toolchain. Supersedes the earlier Next.js sketch |
| D11 | IDs: ULID strings. Naming: "Decisions" = project decisions; policy allow/deny = "Approvals & Audit" | Sortable IDs; no vocabulary collision |
| D12 | Single server, localhost bind, default port 4400 | Local-first identity |
| D13 | External coding agents (Claude Code, Codex, Cursor, …) are first-class: they consume Drydock via MCP, are governed via aegis hooks into the same audit/ask tables, and can BE the execution engine for a run via the Runner protocol | Devs keep the agents they already use; Drydock supplies workspace + policy + PM |

---

## 2. Repo layout

```
drydock/
  pyproject.toml            # name=drydock-ai; [project.scripts] drydock=drydock.cli:main
  DESIGN.md                 # this file
  drydock/
    cli.py                  # up | init | run | agent | policy | tier | doctor
    config.py               # data dir resolution, settings, first-run state
    store/                  # ── ported from orbit pmhub_core ──
      db.py                 #   sqlite3 conn factory, WAL, migration runner
      schema.sql            #   flattened schema (§3)
      service.py            #   dual-write contract (SQLite + optional Chroma)
      fts.py                #   FTS5 + RRF hybrid search (port of tsvector queries)
      chroma.py             #   embedded PersistentClient (optional)
      embeddings.py         #   tiered: none / ollama / fastembed
      allocator.py          #   knapsack budget allocator (near-verbatim port)
      memory.py             #   memories, decisions, handoffs, pins
      tickets.py            #   tickets, work_items, file scopes
      planning.py           #   task_brief, create_ticket_from_plan, assign_files
      registry.py           #   agents + skills (upsert-by-name, versioned)
      graph.py              #   entities, relationships
      observability.py      #   runs, run_events, audit queries, token rollups
    runtime/                # ── greenfield ──
      session.py            #   agent loop (stream → tool_use → dispatch → repeat)
      providers/anthropic.py, openai_compat.py
      tools/                #   read, write, edit, ls_glob, grep, bash, git, task_done
      toolbus.py            #   dispatch: kernel.check → worker.exec → audit → result
      kernel.py             #   aegis integration (§5)
      agentdef.py           #   .md frontmatter ↔ registry ↔ compiled aegis policy
      budget.py             #   per-run token/cost ceilings
    sandbox/
      base.py               #   WorkspaceProvider + Worker protocols
      worker.py             #   tool executor (runs inside the sandbox; JSON-RPC stdio)
      tier0.py              #   in-process worker, scrubbed env, realpath containment
      tier1_wsl.py          #   WSL distro provision/exec (git bundle in, patch out)
      tier2_docker.py       #   container exec (post-v0.1)
      worktree.py           #   git worktree per run; merge/discard flows
      detect.py             #   wsl --status, docker info, ollama, git
    server/
      app.py                #   FastAPI: REST + SSE + static UI mount
      routes/…              #   §6
      approvals.py          #   asks queue, resolution, run resume
    mcp/server.py           #   FastMCP stdio (§7)
  ui/                       # Next.js; `next build` output committed into wheel data
  policies/default.yaml     # shipped default project policy
  tests/
```

Data dir: `%USERPROFILE%\.drydock\` → `drydock.db`, `chroma/`, `keys/`, `logs/`.
Per-repo: `.drydock/` → `policy.yaml`, `agents/*.md`, `settings.json`.

---

## 3. Data model (SQLite, flattened from orbit's 22 migrations)

All PKs `TEXT` ULID unless noted. `*_at` = ISO-8601 UTC.

### PM plane (ported)
```sql
projects      (id, slug UNIQUE, name, root_path, primary_repo_id, settings_json, created_at)
repos         (id, project_id→projects, path, name, is_primary INT)
tickets       (id, project_id, number INT,            -- per-project sequence → "TCK-102"
               title, body, status TEXT,              -- open|ready|in_progress|review|done|archived
               priority INT,                          -- 0=P0..3=P3
               assignee_agent_id NULL→agents, plan_json, created_at, updated_at)
work_items    (id, ticket_id→tickets, title, status, ord INT, files_json)
file_scopes   (id, ticket_id, path, reason)           -- orbit assign_files
memories      (id, project_id, kind, title, body, source, importance REAL,
               chroma_id NULL, created_at, decayed_at NULL)
decisions     (id, project_id, title, body, status,   -- active|superseded
               supersedes_id NULL, ticket_id NULL, created_at)
handoffs      (id, project_id, body, status,          -- active|consumed
               run_id NULL, created_at)
pins          (id, project_id, target_type, target_id, created_at)
entities      (id, project_id, kind, name, meta_json) -- file|module|concept|agent
relationships (id, project_id, src→entities, dst→entities, kind, weight REAL)
skills        (id, project_id, name, description, body, steps_json, level)
```
FTS5 virtual tables + sync triggers: `memories_fts`, `tickets_fts`, `decisions_fts`.
Hybrid search = FTS5 bm25 ⊕ vector cosine, fused with RRF (port of orbit's ranking).

### Agents & runtime (new)
```sql
agents        (id, project_id NULL,                   -- NULL = global agent
               name UNIQUE-per-scope, description, definition_md, model,
               tools_json, policy_yaml,               -- compiled from frontmatter
               version INT, created_at, updated_at)
runs          (id, project_id, agent_id, ticket_id NULL, workspace_id,
               status TEXT,                           -- queued|running|waiting|done|failed|killed
               tier INT, model, started_at, ended_at,
               tokens_in INT, tokens_out INT, cost_cents INT, summary)
run_events    (id, run_id, seq INT, type TEXT,        -- message|tool_call|tool_result|decision|status
               payload_json, ts)                      -- the transcript + SSE source
workspaces    (id, project_id, run_id NULL, tier INT,
               kind TEXT,                             -- worktree|dir|wsl|container
               path, wsl_distro NULL, container_id NULL,
               base_commit, branch, status TEXT,      -- active|merged|discarded
               created_at)
```

### Governance (aegis sink, new)
```sql
audit         (id, run_id NULL, ext_session_id NULL,  -- ext = Claude Code hook capture
               ts, event, tool, action, decision TEXT,-- allow|deny|ask
               rule, message, args_json, identity, tokens_json)
asks          (id, run_id, audit_id→audit, status TEXT,-- pending|approved_once|always|denied|expired
               resolved_by NULL, resolved_at NULL, expires_at)
policy_grants (id, project_id, agent_id NULL, rule, scope_json, created_by, created_at)
                                                      -- persisted "always allow" answers
```

`audit` receives **both** native runtime decisions and external aegis hook events
(Claude Code sessions on the same machine) — one blame/rap-sheet story for everything.

---

## 4. Runtime

**Loop** (`session.py`): build system prompt (agent definition + `task_brief(ticket)` assembled
under token budget by `allocator`) → stream from provider → on `tool_use`: `toolbus.dispatch`
→ append `tool_result` → repeat. Terminates on `task_done(summary)`, max_turns, budget ceiling,
kill, or terminal error. On any exit: write summary → `runs`, auto-draft `handoff` if unfinished.

**Toolbus dispatch — every call, no exceptions:**
```
tool_call → kernel.check(event)            # host-side aegis
  allow → worker.exec(tool, args)          # inside sandbox
  deny  → tool_result(error, rule message) # model sees why, can adapt
  ask   → asks row + SSE notify + run.status=waiting … resume on resolution
→ audit row (always) → run_events row (always)
```

**Tools v1**: `read_file`, `write_file`, `edit_file`, `ls`, `glob`, `grep`, `bash`,
`git_status`, `git_diff`, `task_done`. Every path realpath-resolved and contained in workspace
root (ported from orbit `codebase.py`). `bash` has timeout + output caps; env scrubbed
(no user HOME creds, no API keys, minimal PATH).

**Agent definition** (`.drydock/agents/refactor-bot.md`):
```markdown
---
name: refactor-bot
description: Small, safe refactors preserving behavior
model: claude-sonnet-5
tools: [read_file, edit_file, grep, glob, bash, git_diff, task_done]
max_turns: 60
budget: {tokens: 200000, cost_usd: 3.00}
permissions:
  default: deny
  rules:
    - {action: read_file,  scope: "ws://**",        decision: allow}
    - {action: edit_file,  scope: "ws://src/**",    decision: allow}
    - {action: bash,       match: "npm test*",      decision: allow}
    - {action: network,    scope: "*",              decision: ask}
---
# Refactor Bot
You make small, incremental changes and preserve external behavior…
```
`agentdef.py` compiles `permissions` → aegis rule objects layered as:
**aegis built-ins (non-escapable) > project policy.yaml > agent frontmatter (default-deny) >
policy_grants (accumulated "always allow")**. Registered into `agents` on load (versioned).

**Asks**: pending ask pauses the run (`waiting`). Resolution via UI/CLI/MCP:
`deny` (tool_result error) · `approve_once` (exec + resume) · `always`
(→ `policy_grants` row + exec + resume). `expires_at` default 60 min → auto-deny, run continues
(model told it timed out).

---

## 5. Policy kernel

- `kernel.py` wraps `aegis.engine.evaluate` in-process; normalized event = aegis generic-adapter
  shape (event/tool/action/args/identity/session). The model never talks to the kernel —
  it only emits tool JSON; the toolbus is the sole execution path.
- Per-run identity: aegis Ed25519 token issued at dispatch (`identity.py` reuse) — audit rows
  attribute to agent + run cryptographically.
- Egress policy from project `policy.yaml` (aegis `egress:` section): Tier 0 enforced by
  aegis command rules (policy-grade); Tier 1 compiled to in-distro firewall rules at provision;
  Tier 2 docker network config.
- aegis JSONL mirror (`~/.aegis/audit.jsonl`) optional via setting, for users already on aegis.

## 6. Sandbox

`WorkspaceProvider.provision(run) → Workspace`, `Worker.exec(tool_call) → result`,
`merge/discard`.

- **Worktree layer (all tiers)**: `git worktree add` from ticket's base commit on branch
  `drydock/tck-<n>-<slug>`. Review = diff in UI → merge or discard.
- **Tier 0**: worker in-process on host. Containment = path realpath checks + scrubbed env +
  aegis rules. README language: "policy-grade, not a VM boundary."
- **Tier 1 (WSL2)**: dedicated distro `drydock` (`drydock tier setup`): imports minimal rootfs,
  writes `/etc/wsl.conf` → `[automount] enabled=false`, `[interop] enabled=false`,
  `appendWindowsPath=false`. Code in: git bundle copied via `\\wsl$\drydock\` (host can write in;
  distro cannot see Windows drives). Worker (`drydock-worker`) runs inside distro, JSON-RPC over
  `wsl -d drydock` stdio. Code out: git bundle/patch → applied to host worktree for review.
- **Tier 2 (Docker, post-v0.1)**: aegis `sandbox/Dockerfile` as base; worker in container;
  `--network none` or egress proxy.
- `detect.py` feeds the wizard + tier badge; workspace rows record actual tier used.

## 7. Server, MCP, CLI

**REST (FastAPI, :4400)** — UI + automation:
```
/api/projects…                          /api/tickets… (+ /{id}/brief, /{id}/dispatch)
/api/memory/search?q=&budget=           /api/memories|decisions|handoffs|pins…
/api/resume                             /api/agents… (+ validate)
/api/runs… (+ /{id}/events SSE, /{id}/kill, /{id}/diff, /{id}/merge)
/api/asks (pending) + /api/asks/{id}/resolve
/api/audit?…                            /api/stats/tokens|outcomes
/api/system/tiers|doctor
```
Static UI mounted at `/`. Localhost bind; no auth by default (local-first), token optional.

**MCP (stdio)**: orbit's 53 tools preserved with same names where possible (resume,
search_context, assemble_context, create_ticket, task_brief, log_decision, create_handoff,
register_agent, …) + new: `dispatch_agent`, `get_run`, `list_asks`, `resolve_ask`,
`workspace_diff`. Claude Code (or any MCP client) gets the full PM + can launch sandboxed runs.

**CLI**:
```
drydock up                    # server + open browser (first-run wizard)
drydock init                  # in a repo: .drydock/, default policy, register project
drydock run <agent> --ticket TCK-100 [--tier 1] [--watch]
drydock agent new|list|test
drydock policy validate|explain
drydock tier setup|status
drydock doctor
```

## 7b. External agents (D13) — Claude Code, Codex, Cursor as citizens

Three surfaces, weakest to strongest coupling:

**1. Client (shipped in Phase 0).** Any MCP client gets the full PM plane:
`claude mcp add drydock -- drydock mcp` (same for Codex `codex mcp add` / Cursor MCP config).
resume/search/tickets/task_brief/log_decision work today. Phase 2 adds dispatch_agent /
list_asks / resolve_ask so an external orchestrator can drive sandboxed runs.

**2. Governed (Phase 2, mostly aegis reuse).** `drydock hooks install`:
- Runs aegis's installer against `.claude/settings.json` (26-event surface) with the audit
  sink pointed at drydock.db (`audit.ext_session_id`) instead of / in addition to JSONL.
- Claude Code sessions on this machine become policed by the project policy and visible in
  Mission Control (blame, rap sheet, token attribution) — zero native-runtime involvement.
- Codex/Cursor/Windsurf: aegis generic JSON adapter where the harness exposes hooks;
  git/CI floor otherwise (aegis ADAPTERS.md matrix applies).
- Ambient capture (orbit's SessionStart/PostToolUse memory hooks) rides the same install.

**3. Runner (Phase 1 protocol, external runners Phase 2).** A run's execution engine is
pluggable — `runs.runner`:
```
Runner.start(run, workspace, brief) -> events     # native | claude | codex | shell
```
- `native`: Drydock's own session loop (§4).
- `claude`: spawns `claude -p "<rendered task_brief>" --output-format stream-json` headless
  inside the provisioned workspace (tier 0/1/2), with hooks pre-installed in the workspace's
  `.claude/settings.json` and MCP pointed back at Drydock. Policy asks from the hook layer
  block on Drydock's ask queue (poll until resolved / timeout deny) — the same Approve-once /
  Always / Deny card in the UI resolves a Claude Code permission as easily as a native one.
- `codex`: same pattern via `codex exec` non-interactive mode + generic adapter.
- `shell`: provision-only. `drydock workspace open TCK-12` prints the sandboxed worktree
  path; the dev launches any agent manually and still gets diff review + merge/discard.

Transcript capture for external runners: stream-json/stdout parsed into `run_events`
best-effort; audit rows come from the hook layer, so governance never depends on parsing.

1. **Overview** — as designed: KPIs, ask hero, Work + Project memory, pipeline/donut/chart,
   agents table, tier banner
2. **Work** — ticket list/board, ticket detail w/ brief + scoped files + dispatch
3. **Memory** — search (hybrid), decisions log, handoffs, pins
4. **Runs** — run viewer: live transcript (run_events SSE), diff review, merge/discard
5. **Approvals & Audit** — pending asks, audit table w/ filters, per-agent rap sheet
6. **Agents** — registry list + definition viewer (Studio editing = post-v0.1)
7. **First-run wizard** — API key → projects folder → tier detection

## 9. Build phases

| Phase | Scope | Exit criterion | Est. |
|---|---|---|---|
| **0 — Foundation** | Scaffold, pyproject, schema.sql, db.py, store port (service/fts/memory/tickets/planning/registry/allocator), config, CLI skeleton, store tests | `drydock init` + MCP resume/search/tickets work against SQLite | ~1.5 wk |
| **1 — Runtime** | providers, session loop, tools, toolbus, kernel(aegis), tier0 + worktrees, runs/run_events, budget, **Runner protocol + shell runner** (`drydock workspace open`) | `drydock run refactor-bot --ticket TCK-1` completes a real ticket headless, fully audited, ask pauses work in CLI | ~1 wk |
| **2 — Server + approvals** ✅ | FastAPI, SSE, asks flow, audit/stats routes, MCP additions, **`drydock hooks install` (aegis→drydock sink) + claude runner** | Dispatch + approve-ask + watch live; a Claude Code run inside a Drydock workspace shows up in the same audit/ask queue | done |
| **3 — UI** ✅ | Hand-crafted static app (no framework/Node), 8 views (Overview, Approvals, Runs+live viewer, Work, Memory, Agents, Studio, Audit, Settings), dispatch modal, real logo | `drydock up` → full flow in browser, verified | done |
| **4 — Tier 1 + release** | WSL worker, distro setup, egress rules, docs, README, PyPI publish | v0.1.0 on PyPI, demo GIF, tier 1 verified on this machine | ~1 wk |

Post-v0.1: Tier 2 Docker, Agent Studio editing UI, skills flywheel, teams/Pro, desktop installer.

## 10. Non-goals (v1)

No cloud/hosted mode · no TUI/IDE plugin · no provider matrix beyond D8 · no Windows Sandbox
(Home) · no microVM · no marketing-pipeline port from orbit (dropped) · no multi-user auth.

## 11. Open items (non-blocking)

- Ask expiry default (60 min auto-deny) — revisit after dogfooding
- Chroma vs sqlite-vec long-term (start Chroma-optional; sqlite-vec would collapse to one file)
- Pro license check placement (offline Ed25519, `drydock license activate`) — Phase 4+
- orbit ambient-capture hooks (Claude Code SessionStart etc.) — port in Phase 2 as optional
  `drydock hooks install`, writing into the same `audit`/`memories` tables
