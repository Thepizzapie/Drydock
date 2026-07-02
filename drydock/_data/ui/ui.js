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
