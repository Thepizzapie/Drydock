// Tiny hyperscript + shared component vocabulary. Views compose with these so
// the whole app stays visually consistent. No framework, no build.

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "dataset") Object.assign(node.dataset, v);
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c == null || c === false) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
}

export const clear = (n) => { while (n.firstChild) n.removeChild(n.firstChild); return n; };

// ---- shared components -----------------------------------------------------

export function card({ title, meta, live, link, onLink, body, flush } = {}) {
  const kids = [];
  if (title || meta || link || live) {
    const hd = el("div", { class: "hd" }, [
      title && el("h3", { text: title }),
      live && el("span", { class: "live", text: "LIVE" }),
      meta && el("span", { class: "meta", text: meta }),
      link && el("a", { class: "link", href: onLink ? "#" : (link.href || "#"),
        onclick: onLink ? (e) => { e.preventDefault(); onLink(); } : null, text: link.text || link }),
    ]);
    kids.push(hd);
  }
  if (body) kids.push(el("div", { class: "bd" + (flush ? " flush" : "") }, body));
  return el("div", { class: "card" }, kids);
}

export function stat({ label, value, cap, attn, icon } = {}) {
  return el("div", { class: "card stat" }, [
    el("div", { class: "lbl" }, [icon, label]),
    el("div", { class: "num" + (attn ? " attn" : ""), text: value }),
    cap && el("div", { class: "cap", text: cap }),
  ]);
}

export function pill(text, kind = "mute") { return el("span", { class: `pill ${kind}`, text }); }
export function badge(decision) {
  const k = decision === "allow" ? "allow" : decision === "deny" ? "deny" : "ask";
  return el("span", { class: `badge ${k}`, text: decision.toUpperCase() });
}

export function btn(text, { kind = "ghost", sm, onClick, icon } = {}) {
  return el("button", { class: `btn ${kind}${sm ? " sm" : ""}`, onclick: onClick }, [icon, text]);
}

export function empty({ title = "Nothing here yet", text = "", icon } = {}) {
  return el("div", { class: "empty" }, [
    icon && el("div", { class: "ic", html: icon }),
    el("h4", { text: title }),
    text && el("p", { text }),
  ]);
}

export function skeleton(rows = 4) {
  return el("div", { class: "bd stack" },
    Array.from({ length: rows }, () => el("div", { class: "skel", style: "height:34px" })));
}

export function bar(pct, kind = "") {
  return el("div", { class: `bar ${kind}` }, [el("i", { style: `width:${Math.max(0, Math.min(100, pct))}%` })]);
}

// ---- helpers ---------------------------------------------------------------

export function relTime(iso) {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (isNaN(t)) return "—";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 45) return "just now";
  if (s < 90) return "1 min ago";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 7200) return "1 hr ago";
  if (s < 86400) return `${Math.round(s / 3600)} hr ago`;
  return `${Math.round(s / 86400)} d ago`;
}
export function clockTime(iso) {
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}
export function fmtTokens(n) {
  n = n || 0;
  if (n >= 1000) return (n / 1000).toFixed(1) + "k";
  return String(n);
}
export function priorityLabel(p) { return "P" + (p ?? 2); }

let _toastHost;
export function toast(msg, kind = "") {
  if (!_toastHost) { _toastHost = el("div", { class: "toasts" }); document.body.append(_toastHost); }
  const t = el("div", { class: `toast ${kind}`, text: msg });
  _toastHost.append(t);
  setTimeout(() => t.remove(), 3200);
}

export function modal({ title, body, actions = [] }) {
  const scrim = el("div", { class: "scrim", onclick: (e) => { if (e.target === scrim) close(); } });
  function onKey(e) { if (e.key === "Escape") close(); }
  function close() { document.removeEventListener("keydown", onKey); scrim.remove(); }
  const m = el("div", { class: "modal", tabindex: "-1" }, [
    el("div", { class: "hd" }, [el("h3", { text: title }),
      el("button", { class: "x", html: ICONS.x, "aria-label": "Close", onclick: close })]),
    el("div", { class: "bd" }, body),
    actions.length && el("div", { class: "ft" }, actions),
  ]);
  scrim.append(m);
  document.body.append(scrim);
  document.addEventListener("keydown", onKey);
  m.focus();
  return { close };
}

// Make a non-button element keyboard-operable (Enter/Space activates onclick).
export function clickable(node, onActivate) {
  node.setAttribute("tabindex", "0");
  node.setAttribute("role", "button");
  node.addEventListener("click", onActivate);
  node.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onActivate(e); }
  });
  return node;
}

// Copy-to-clipboard button for command snippets.
export function copyBtn(text) {
  return btn("Copy", { kind: "ghost", sm: true, onClick: async (e) => {
    try { await navigator.clipboard.writeText(text); toast("Copied", "ok"); }
    catch { toast("Couldn't copy — select it manually", "err"); }
  } });
}

// Shared new-project flow (topbar + settings). Registers a repo path as a project.
export async function projectModal(state, { onCreated } = {}) {
  const { api } = await import("./api.js");
  const nameInput = el("input", { class: "input", placeholder: "e.g. Shipping Platform" });
  const pathInput = el("input", { class: "input", placeholder: "e.g. D:\\shipping-platform (repo root)" });
  const prefixInput = el("input", { class: "input", placeholder: "auto — e.g. SP", maxlength: "6" });

  const field = (label, control, hint) => el("label", { style: "display:block;margin-bottom:14px" }, [
    el("div", { style: "font-size:12px;font-weight:600;color:var(--ink-2);margin-bottom:5px", text: label }),
    control,
    hint && el("div", { class: "muted", style: "font-size:11.5px;margin-top:4px", text: hint }),
  ]);

  const go = btn("Register project", { kind: "primary", onClick: async () => {
    const name = nameInput.value.trim();
    if (!name) { toast("Give the project a name", "err"); return; }
    go.disabled = true; go.textContent = "Registering…";
    try {
      const p = await api.createProject({ name, root_path: pathInput.value.trim() || null,
                                          ticket_prefix: prefixInput.value.trim() || null });
      m.close();
      toast(`Registered ${p.slug}`, "ok");
      if (onCreated) onCreated(p);
    } catch (e) { toast(e.message, "err"); go.disabled = false; go.textContent = "Register project"; }
  } });

  const m = modal({
    title: "New project",
    body: [
      el("p", { class: "muted", style: "margin:0 0 16px;line-height:1.5",
        text: "Point Drydock at a repo. Tickets, memory, runs, and audit all scope to it." }),
      field("Name", nameInput),
      field("Repo path", pathInput, "Optional — without it you get PM only (no sandboxes or code view)."),
      field("Ticket prefix", prefixInput, "Keys look like SP-1, SP-2. Left blank, it's derived from the name."),
    ],
    actions: [btn("Cancel", { kind: "ghost", onClick: () => m.close() }), go],
  });
}

// Agent builder — author an agent in-app: model (cloud OR local), tools it may
// use, and the permission rules that gate them. This is the "create your own
// local agent" surface. `existing` prefills for editing. Writes a real .md file.
export async function agentAuthorModal(state, { existing, onSaved } = {}) {
  const { api } = await import("./api.js");
  const [catalog, toolList] = await Promise.all([
    api.models().catch(() => ({ cloud: [], local: { available: false, models: [] } })),
    api.tools().catch(() => []),
  ]);
  const def = (existing && existing.definition) || {};
  const perms = def.permissions || { default: "deny", rules: [] };

  const nameIn = el("input", { class: "input", value: existing ? existing.name : "",
    placeholder: "e.g. test-writer", disabled: existing ? "disabled" : null });
  const descIn = el("input", { class: "input", value: existing ? (existing.description || "") : "",
    placeholder: "one line — what this agent is for" });

  // model select: cloud group + detected local group
  const modelSel = el("select", { class: "input" });
  const cur = existing ? existing.model : null;
  for (const m of catalog.cloud || [])
    modelSel.append(el("option", { value: m.id, text: `${m.label}  ·  cloud`, selected: m.id === cur ? "selected" : null }));
  const locals = (catalog.local && catalog.local.models) || [];
  for (const m of locals)
    modelSel.append(el("option", { value: m.id, text: `${m.label}  ·  local · free`, selected: m.id === cur ? "selected" : null }));
  const localNote = catalog.local && catalog.local.available
    ? el("div", { class: "muted", style: "font-size:11.5px;margin-top:4px",
        text: `${locals.length} local model${locals.length === 1 ? "" : "s"} detected at ${catalog.local.endpoint} — runs free and offline.` })
    : el("div", { class: "muted", style: "font-size:11.5px;margin-top:4px",
        text: "No local model server detected. Start Ollama (or any OpenAI-compatible server) to run agents on your own hardware." });

  const promptIn = el("textarea", { class: "textarea", style: "min-height:90px",
    text: existing ? (def.__body || "") : "" ,
    placeholder: "System prompt — how this agent should work, what to prefer, what to avoid." });

  // tools: checkboxes
  const curTools = new Set(existing ? (existing.tools || []) : ["read_file", "edit_file", "grep", "glob", "task_done"]);
  const toolBoxes = toolList.map((t) => {
    const cb = el("input", { type: "checkbox", checked: curTools.has(t.name) ? "checked" : null });
    cb._tool = t.name;
    return el("label", { style: "display:flex;gap:8px;align-items:flex-start;font-size:12.5px;padding:5px 0" },
      [cb, el("div", {}, [el("span", { class: "mono", style: "font-weight:600", text: t.name }),
        el("div", { class: "muted", style: "font-size:11.5px", text: t.description })])]);
  });

  // permission rules
  const ruleRows = [];
  const rulesHost = el("div", { class: "stack", style: "gap:6px" });
  const toolOpts = ["read_file", "write_file", "edit_file", "bash", "glob", "grep", "git_status", "git_diff", "network"];
  function addRule(r = {}) {
    const act = el("select", { class: "input mono", style: "font-size:12px" },
      toolOpts.map((t) => el("option", { value: t, text: t, selected: (r.action === t) ? "selected" : null })));
    const scope = el("input", { class: "input mono", style: "font-size:12px", value: r.scope || r.match || "",
      placeholder: "scope e.g. src/** — or a command match" });
    const dec = el("select", { class: "input", style: "font-size:12px" },
      ["allow", "ask", "deny"].map((d) => el("option", { value: d, text: d, selected: (r.decision === d) ? "selected" : null })));
    const entry = { act, scope, dec, row: null };
    const rm = btn("×", { kind: "ghost", sm: true, onClick: () => { const i = ruleRows.indexOf(entry); if (i > -1) ruleRows.splice(i, 1); entry.row.remove(); } });
    entry.row = el("div", { style: "display:grid;grid-template-columns:1.1fr 1.6fr .9fr auto;gap:6px;align-items:center" }, [act, scope, dec, rm]);
    ruleRows.push(entry);
    rulesHost.append(entry.row);
  }
  (perms.rules || []).forEach(addRule);
  if (!(perms.rules || []).length) { addRule({ action: "read_file", scope: "**", decision: "allow" }); addRule({ action: "bash", scope: "*", decision: "ask" }); }

  const defaultSel = el("select", { class: "input", style: "width:auto" },
    ["deny", "ask", "allow"].map((d) => el("option", { value: d, text: `default: ${d}`, selected: (perms.default || "deny") === d ? "selected" : null })));

  const field = (label, control, hint) => el("label", { style: "display:block;margin-bottom:14px" }, [
    el("div", { style: "font-size:12px;font-weight:600;color:var(--ink-2);margin-bottom:5px", text: label }),
    control, hint,
  ]);
  const section = (label) => el("div", { style: "font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);margin:6px 0 8px", text: label });

  const go = btn(existing ? "Save agent" : "Create agent", { kind: "primary", onClick: async () => {
    const name = nameIn.value.trim();
    if (!name) { toast("Give the agent a name", "err"); return; }
    const tools = toolBoxes.map((l) => l.querySelector("input")).filter((c) => c.checked).map((c) => c._tool);
    if (!tools.includes("task_done")) tools.push("task_done");
    const rules = ruleRows.map((e) => {
      const scope = e.scope.value.trim();
      const r = { action: e.act.value, decision: e.dec.value };
      if (scope) { if (e.act.value === "bash") r.match = scope; else r.scope = scope; }
      return r;
    });
    go.disabled = true; go.textContent = "Saving…";
    try {
      const row = await api.authorAgent(state.project, {
        name, description: descIn.value.trim(), model: modelSel.value,
        tools, system_prompt: promptIn.value,
        permissions: { default: defaultSel.value, rules },
      });
      m.close();
      toast(existing ? "Agent saved" : `Created ${row.name}`, "ok");
      if (onSaved) onSaved(row);
    } catch (e) { toast(e.message, "err"); go.disabled = false; go.textContent = existing ? "Save agent" : "Create agent"; }
  } });

  const m = modal({
    title: existing ? `Edit ${existing.name}` : "New agent",
    body: [
      el("p", { class: "muted", style: "margin:0 0 16px;line-height:1.5",
        text: "Agents run in a sandbox with only the tools and permissions you grant. Pick a cloud or local model — Drydock routes either." }),
      field("Name", nameIn),
      field("Description", descIn),
      field("Model", modelSel, localNote),
      field("System prompt", promptIn),
      section("Tools it may use"),
      el("div", { style: "columns:2;column-gap:20px;margin-bottom:14px" }, toolBoxes),
      el("div", { class: "row-between", style: "margin-bottom:8px" }, [section("Permissions"), defaultSel]),
      el("div", { class: "muted", style: "font-size:11.5px;margin-bottom:8px",
        text: "Rules match top-down. A file rule uses a path scope (src/**); a bash rule matches the command (npm test*)." }),
      rulesHost,
      el("div", { style: "margin-top:8px" }, [btn("+ Add rule", { kind: "ghost", sm: true, onClick: () => addRule() })]),
    ],
    actions: [btn("Cancel", { kind: "ghost", onClick: () => m.close() }), go],
  });
}

// Shared dispatch flow — pick an agent (+ optional ticket + tier), start a run,
// jump to its live transcript. Wired from every "Dispatch agent" affordance so
// the core loop (ticket → dispatch → watch → approve → review) actually closes.
export async function dispatchModal(state, { ticket, navigate } = {}) {
  const { api } = await import("./api.js");
  let agents = [];
  try { agents = await api.agents(state.project); } catch (_) {}
  if (!agents.length) {
    modal({ title: "No agents to dispatch",
      body: [el("p", { class: "muted", style: "margin:0;line-height:1.55",
        text: "Register an agent first, then dispatch it. Author one as Markdown and run:" }),
        el("div", { class: "code", style: "margin-top:10px" }, [el("pre", { text: "drydock agent add path/to/agent.md" })])],
      actions: [btn("Got it", { kind: "primary", onClick: () => document.querySelector(".scrim")?.remove() })] });
    return;
  }

  const recTier = (state.tiers && state.tiers.recommended) ?? 0;
  const agentSel = el("select", { class: "input" }, agents.map((a) =>
    el("option", { value: a.name, text: `${a.name}${a.model ? " · " + a.model : ""}` })));
  const ticketInput = el("input", { class: "input", value: ticket || "", placeholder: "optional — e.g. SP-3" });
  const tierSel = el("select", { class: "input" }, [
    el("option", { value: "0", text: "Tier 0 · policy-only" }),
    el("option", { value: "1", text: "Tier 1 · WSL2", selected: recTier === 1 ? "selected" : null }),
    el("option", { value: "2", text: "Tier 2 · Docker", selected: recTier === 2 ? "selected" : null }),
  ]);

  const field = (label, control) => el("label", { style: "display:block;margin-bottom:14px" }, [
    el("div", { style: "font-size:12px;font-weight:600;color:var(--ink-2);margin-bottom:5px", text: label }), control]);

  const go = btn("Dispatch", { kind: "primary", onClick: async () => {
    go.disabled = true; go.textContent = "Dispatching…";
    try {
      const out = await api.dispatch(state.project, {
        agent: agentSel.value, ticket: ticketInput.value.trim() || null, tier: Number(tierSel.value) });
      m.close();
      toast("Agent dispatched", "ok");
      if (out.run_id && navigate) navigate("#/run/" + out.run_id);
    } catch (e) { toast(e.message, "err"); go.disabled = false; go.textContent = "Dispatch"; }
  } });

  const m = modal({
    title: "Dispatch an agent",
    body: [
      el("p", { class: "muted", style: "margin:0 0 16px;line-height:1.5",
        text: "The agent runs in an isolated sandbox against a fresh worktree. You'll watch it live and approve anything policy holds." }),
      field("Agent", agentSel),
      field("Ticket", ticketInput),
      field("Isolation tier", tierSel),
    ],
    actions: [btn("Cancel", { kind: "ghost", onClick: () => m.close() }), go],
  });
}

// ---- icon set (stroke, currentColor) --------------------------------------
export const ICONS = {
  overview: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3.5" y="3.5" width="7" height="7" rx="2"/><rect x="13.5" y="3.5" width="7" height="7" rx="2"/><rect x="3.5" y="13.5" width="7" height="7" rx="2"/><rect x="13.5" y="13.5" width="7" height="7" rx="2"/></svg>',
  ask: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 3a9 9 0 1 0 4.5 16.8L21 21l-1.2-4.5A9 9 0 0 0 12 3Z"/><path d="M9.5 9.5a2.5 2.5 0 0 1 4.2 1.8c0 1.7-2.2 1.7-2.2 3M11.6 16h.01"/></svg>',
  audit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h8M8 16h5"/></svg>',
  ticket: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M4 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v3a2 2 0 0 0 0 4v3a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-3a2 2 0 0 0 0-4z"/><path d="M13 5v14" stroke-dasharray="2 2"/></svg>',
  memory: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3.5 2"/></svg>',
  runs: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M6 4l14 8-14 8z"/></svg>',
  studio: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M14.5 4.5l5 5L9 20H4v-5z"/><path d="M12.5 6.5l5 5"/></svg>',
  settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="3.2"/><path d="M12 3v3M12 18v3M4.2 7.5l2.6 1.5M17.2 15l2.6 1.5M4.2 16.5l2.6-1.5M17.2 9l2.6-1.5"/></svg>',
  agents: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="5" y="8" width="14" height="10" rx="2.5"/><path d="M12 8V4.5M8.5 13h.01M15.5 13h.01M9 18v2M15 18v2"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  windows: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 5.5l8-1.1v7.1H3zM12 4.2L21 3v8.5h-9zM3 12.5h8v7.1l-8-1.1zM12 12.5h9V21l-9-1.3z"/></svg>',
  diff: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M6 3v12a3 3 0 0 0 3 3h6M18 21V9a3 3 0 0 0-3-3H9"/><path d="M4 6h4M16 18h4"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>',
  // Drydock mark: navy ship in a steel-blue keel cradle, flanked by dock walls.
  ship: '<svg viewBox="0 0 120 112" fill="none"><g fill="#0B1D33"><path d="M52 6h16v16h16v10H36V22h16z"/><path d="M40 34h40l-6 34a14 14 0 0 1-28 0z"/><path d="M14 44h13v42H14zM93 44h13v42H93z"/></g><g fill="#3B5168"><path d="M30 62h60l-8 12H38z"/><path d="M27 62l14 14H27zM93 62L79 76h14z"/></g><rect x="10" y="90" width="100" height="9" fill="#0B1D33"/></svg>',
};
