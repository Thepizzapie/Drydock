# Drydock dashboard — build spec for view modules

Hand-crafted static app (vanilla ES modules + CSS tokens). **No framework, no build, no npm.**
Every view is one function that renders into a container. Match the reference exactly:
`views/overview.js` is the gold standard for layout rhythm, component use, and copy voice.

## Non-negotiables

1. **Read these first**: `app.css` (all classes + tokens), `ui.js` (helpers/components),
   `api.js` (endpoints), and `views/overview.js` (reference). Reuse their vocabulary.
2. **Never hardcode a color.** Use CSS tokens/classes only. If you need a new color, you're
   doing it wrong — there is a class for it.
3. **Build DOM with `el()`** from `ui.js` (hyperscript). No template-string innerHTML for
   structure (only `html:` for tiny inline spans/icons, and always escape untrusted text).
4. **Use shared components**: `card()`, `stat()`, `pill()`, `badge()`, `btn()`, `empty()`,
   `skeleton()`, `bar()`, `modal()`, `toast()`, and helpers `relTime()`, `clockTime()`,
   `fmtTokens()`, `ICONS`.
5. **Every view signature**: `export async function xView(root, { rest, params, state }) {}`.
   `state.project` is the current project slug (may be null → render a friendly empty state,
   see overview.js `noProject()`). `rest` = path segments after the route name.
6. **Navigation**: `import { navigate } from "../router.js"` then `navigate("#/runs")` etc.
7. **Loading**: append a `skeleton()` while awaiting, then replace. Wrap `await` in try/catch
   and show `empty({title, text})` on error. Never leave a blank screen.
8. **Copy voice**: plain, active, specific. Errors say what happened + how to fix. Empty states
   invite an action. Sentence case. No filler. (See overview.js.)
9. **Page header**: start each view with the `.page-h` block (title + one-line sub + right
   actions) exactly like overview.js.

## Palette meaning (already in tokens)

- **green (`ok`/`allow`)** = permitted / running / healthy
- **red (`deny`)** = blocked / denied / error
- **orange (`ask`, the brand accent)** = needs a human decision / attention
- **navy** = structure, primary text, primary buttons
- Semantic colors are for state; navy/orange carry brand. Ration them.

## API (see api.js for the full list)

`api.overview(p)`, `api.tickets(p, status?)`, `api.ticket(p, ref)`, `api.memorySearch(p, q, k?)`,
`api.decisions(p)`, `api.runs(p, status?)`, `api.run(id)`, `api.runDiff(id)`, `api.audit(p, decision?)`,
`api.tokens(p)`, `api.asks(p?)`, `api.resolveAsk(id, resolution)`, `api.dispatch(p, body)`,
`api.agents(p)`, `api.agent(p, name)`, `api.tiers()`, `api.doctor()`.
Live run transcript: `import { streamRun } from "../api.js"` → `streamRun(runId, onEvent, onEnd)`.

`resolveAsk` resolution ∈ `"approved_once" | "always" | "denied"`.
Run event types (from `api.run(id).events[].type`): `message | tool_call | tool_result | decision | status`.
Each event: `{ seq, type, payload, ts }`. Run status ∈ `queued|running|waiting|done|failed|killed`.

## Data shapes (fields you'll use)

- ticket: `{ key, title, body, status, priority (0..3), assignee_agent_id }`
- run: `{ id, agent_id, ticket_id, status, runner, tier, tokens_in, tokens_out, cost_cents, summary, started_at, workspace_id }`
- audit row: `{ ts, tool, action, decision (allow|deny|ask), rule, message, args_json, identity, run_id, ext_session_id }`
  — parse `args_json` for `file_path` / `path` / `command`; `identity` looks like `agent@abc123` (split on `@`).
- ask (with detail): `{ id, run_id, status, created_at, detail: <audit row> }`
- agent: `{ name, description, model, tools (list), definition (frontmatter dict), version, policy_yaml }`
- decision: `{ title, rationale, status, created_at }`
- memory hit: `{ id, title, body, kind, importance, pinned, tags }`

## Isolation tiers (for badges / settings)

Tier 0 = policy-only (no VM boundary). Tier 1 = WSL2 VM boundary. Tier 2 = Docker.
Always state Tier 0 is "policy-grade, not a VM boundary" where relevant — honesty is the brand.
