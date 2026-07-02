// Approvals + Audit — human-in-the-loop governance.
// Approvals is the product's differentiator: one focal ask you decide on, now.
// Audit is the permanent local record of every decision your agents made.
import { api } from "../api.js";
import { el, card, pill, badge, btn, empty, skeleton, relTime, clockTime, ICONS, toast, clickable } from "../ui.js";
import { navigate } from "../router.js";

// ============================================================================
// Approvals
// ============================================================================
export async function approvalsView(root, { state }) {
  if (!state.project) { root.append(noProject()); return; }

  const header = el("div", { class: "page-h" }, [
    el("div", {}, [
      el("h2", { class: "t", text: "Approvals" }),
      el("div", { class: "sub", text: "Actions your agents paused on, waiting for a human to decide." }),
    ]),
    el("div", { class: "actions" }, [
      btn("Refresh", { kind: "ghost", onClick: () => reload() }),
    ]),
  ]);
  root.append(header);

  const body = el("div", { class: "stack" });
  root.append(body);

  async function reload() {
    clear(body);
    const loading = el("div", { class: "stack" }, [skeleton(2), skeleton(3)]);
    body.append(loading);

    let asks;
    try { asks = await api.asks(state.project); }
    catch (e) {
      loading.replaceWith(el("div", { class: "card" }, [el("div", { class: "bd" }, [
        empty({ title: "Couldn't load approvals", text: e.message + " — check the server is running, then refresh.", icon: ICONS.ask }),
      ])]));
      return;
    }
    loading.remove();

    // oldest-first: the queue you work top-down
    const pending = asks.filter((a) => a.status === "pending" || a.status == null);
    pending.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

    if (!pending.length) {
      body.append(el("div", { class: "card" }, [el("div", { class: "bd" }, [
        empty({
          title: "Nothing to approve",
          text: "Your agents are running within policy. Approvals appear here the moment one needs a human.",
          icon: ICONS.ask,
        }),
      ])]));
      return;
    }

    const [focal, ...rest] = pending;
    body.append(heroAsk(focal, () => reload()));

    if (rest.length) {
      const list = el("div", {});
      rest.forEach((a) => list.append(askItem(a)));
      body.append(card({
        title: "Also waiting",
        meta: `${rest.length} more`,
        body: [list],
        flush: true,
      }));
    }
  }

  reload();
}

// The single-focus approval — dark navy glass card, the signature element.
function heroAsk(ask, onResolved) {
  const d = ask.detail || {};
  const args = safeParse(d.args_json);
  const target = args.command || args.file_path || args.path || d.tool || "this action";

  const node = el("div", { class: "glass" }, [
    el("div", { class: "k", text: "NEEDS YOUR APPROVAL" }),
    el("h3", { text: `${agentLabel(d.identity)} wants to ${(d.action || "run").toLowerCase()}` }),
    el("div", { class: "sub", text: d.message || "This action fell outside policy and paused for a human decision." }),

    el("div", { style: "margin-top:14px" }, [
      kv("Target", String(target).slice(0, 120)),
      d.rule && kv("Rule that fired", d.rule),
      kv("Tool", d.tool || "—"),
      kv("Workspace / run", d.run_id || ask.run_id || "—"),
      kv("Requested", relTime(ask.created_at)),
    ]),

    el("div", { class: "acts" }, [
      btn("Deny", { kind: "danger", onClick: () => resolve(ask.id, "denied", node, onResolved) }),
      btn("Approve once", { kind: "accent", onClick: () => resolve(ask.id, "approved_once", node, onResolved) }),
      btn("Always allow", { kind: "ghost", onClick: () => resolve(ask.id, "always", node, onResolved) }),
    ]),
  ]);
  return node;
}

function kv(k, v) {
  return el("div", { class: "kv" }, [el("span", { text: k }), el("span", { text: v })]);
}

// A waiting ask in the "Also waiting" list.
function askItem(ask) {
  const d = ask.detail || {};
  const args = safeParse(d.args_json);
  const target = args.command || args.file_path || args.path || d.tool || "action";
  const node = el("div", { class: "ask-item" }, [
    el("div", { class: "top" }, [
      el("span", { class: "who", text: agentLabel(d.identity) }),
      pill(d.action || "action", "ask"),
      el("span", { class: "age", text: relTime(ask.created_at) }),
    ]),
    el("div", { class: "what", html: `${escapeHtml(d.message || "Needs your approval")} <code>${escapeHtml(String(target).slice(0, 70))}</code>` }),
    el("div", { class: "acts" }, [
      btn("Deny", { kind: "danger", sm: true, onClick: () => resolve(ask.id, "denied", node) }),
      btn("Approve once", { kind: "accent", sm: true, onClick: () => resolve(ask.id, "approved_once", node) }),
      btn("Always allow", { kind: "ghost", sm: true, onClick: () => resolve(ask.id, "always", node) }),
    ]),
  ]);
  return node;
}

async function resolve(id, resolution, node, onResolved) {
  node.querySelectorAll("button").forEach((b) => (b.disabled = true));
  try {
    await api.resolveAsk(id, resolution);
    const msg = resolution === "denied" ? "Denied" : resolution === "always" ? "Always allowed" : "Approved once";
    toast(msg, resolution === "denied" ? "err" : "ok");
    node.style.opacity = ".4";
    node.style.pointerEvents = "none";
    if (onResolved) setTimeout(onResolved, 450);
  } catch (e) {
    toast(e.message, "err");
    node.querySelectorAll("button").forEach((b) => (b.disabled = false));
  }
}

// ============================================================================
// Audit
// ============================================================================
const TABS = [
  { key: "all", label: "All", decision: null },
  { key: "allow", label: "Allowed", decision: "allow" },
  { key: "deny", label: "Denied", decision: "deny" },
  { key: "ask", label: "Asks", decision: "ask" },
];

const SOURCES = [
  { value: "", label: "All sources" },
  { value: "native", label: "Native runs" },
  { value: "external", label: "External sessions" },
];

export async function auditView(root, { state }) {
  if (!state.project) { root.append(noProject()); return; }

  root.append(el("div", { class: "page-h" }, [
    el("div", {}, [
      el("h2", { class: "t", text: "Audit" }),
      el("div", { class: "sub", text: "Every decision your agents made, recorded locally." }),
    ]),
  ]));

  let active = "all";
  let facetsLoaded = false;

  const seg = el("div", { class: "seg" }, TABS.map((t) =>
    el("button", {
      class: t.key === active ? "on" : "",
      text: t.label,
      onclick: () => select(t.key),
    })));

  const selStyle = "width:auto;min-width:132px";
  const agentSel = el("select", { class: "input", style: selStyle, "aria-label": "Filter by agent", onchange: () => load() },
    [el("option", { value: "", text: "All agents" })]);
  const toolSel = el("select", { class: "input", style: selStyle, "aria-label": "Filter by tool", onchange: () => load() },
    [el("option", { value: "", text: "All tools" })]);
  const sourceSel = el("select", { class: "input", style: selStyle, "aria-label": "Filter by source", onchange: () => load() },
    SOURCES.map((s) => el("option", { value: s.value, text: s.label })));

  root.append(el("div", { style: "display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px" },
    [seg, agentSel, toolSel, sourceSel]));

  const host = el("div", {});
  root.append(host);

  function select(key) {
    if (key === active) return;
    active = key;
    seg.querySelectorAll("button").forEach((b, i) => b.classList.toggle("on", TABS[i].key === key));
    load();
  }

  function currentFilters() {
    const tab = TABS.find((t) => t.key === active);
    return { decision: tab.decision, agent: agentSel.value, tool: toolSel.value, source: sourceSel.value };
  }
  const isFiltered = (f) => Boolean(f.decision || f.agent || f.tool || f.source);

  // Fill the agent/tool selects once, from the first unfiltered result set.
  function populateFacets(rows) {
    facetsLoaded = true;
    const agents = [...new Set(rows.map((r) => rawAgent(r.identity)).filter(Boolean))].sort();
    const tools = [...new Set(rows.map((r) => r.tool).filter(Boolean))].sort();
    agents.forEach((a) => agentSel.append(el("option", { value: a, text: agentLabel(a) })));
    tools.forEach((t) => toolSel.append(el("option", { value: t, text: t })));
  }

  async function load() {
    clear(host);
    host.append(el("div", { class: "card" }, [skeleton(6)]));

    const filters = currentFilters();
    let rows;
    try { rows = await api.audit(state.project, filters); }
    catch (e) {
      clear(host);
      host.append(el("div", { class: "card" }, [el("div", { class: "bd" }, [
        empty({ title: "Couldn't load the audit trail", text: e.message + " — check the server is running, then reselect a tab.", icon: ICONS.audit }),
      ])]));
      return;
    }

    if (!facetsLoaded && !isFiltered(filters)) populateFacets(rows);

    clear(host);
    if (!rows.length) {
      host.append(el("div", { class: "card" }, [el("div", { class: "bd" }, [
        empty({
          title: isFiltered(filters) ? "No matching decisions" : "No decisions yet",
          text: isFiltered(filters)
            ? "Nothing matched these filters. Loosen one and the rest comes back."
            : "Dispatch an agent and every action it takes is recorded here.",
          icon: ICONS.audit,
        }),
      ])]));
      return;
    }

    host.append(card({
      meta: `${rows.length} ${rows.length === 1 ? "event" : "events"} · click a row for detail`,
      body: [auditTable(rows)], flush: true,
    }));
  }

  load();
}

function auditTable(rows) {
  const head = el("thead", {}, [el("tr", {}, [
    el("th", { text: "Time" }),
    el("th", { text: "Agent" }),
    el("th", { text: "Action" }),
    el("th", { text: "Resource" }),
    el("th", { text: "Rule" }),
    el("th", { text: "Decision", class: "r" }),
  ])]);
  const tb = el("tbody", {});
  rows.forEach((r) => {
    const detail = detailRow(r);
    const tr = el("tr", { style: "cursor:pointer", "aria-expanded": "false" }, [
      el("td", { class: "mono", text: clockTime(r.ts) }),
      el("td", { class: "mono" }, [
        agentLabel(r.identity),
        r.ext_session_id && el("span", { style: "margin-left:6px" }, [pill("external", "info")]),
      ]),
      el("td", { text: r.action || "—" }),
      el("td", { class: "mono", text: resourceLabel(r) }),
      el("td", { class: "muted", text: r.decision !== "allow" ? (r.rule || "—") : "" }),
      el("td", { class: "r" }, [r.decision ? badge(r.decision) : el("span", { class: "muted", text: "—" })]),
    ]);
    clickable(tr, () => {
      detail.hidden = !detail.hidden;
      tr.setAttribute("aria-expanded", detail.hidden ? "false" : "true");
    });
    tb.append(tr, detail);
  });
  return el("table", { class: "tbl" }, [head, tb]);
}

// The expanded record beneath a row — full args, rule + message, identity, run link.
function detailRow(r) {
  const args = safeParse(r.args_json);
  const facts = [];
  if (r.rule) facts.push(["Rule", r.rule]);
  if (r.message) facts.push(["Message", r.message]);
  facts.push(["Identity", r.identity || "system"]);
  if (r.ext_session_id) facts.push(["External session", r.ext_session_id]);

  const cell = el("td", { colspan: "6", style: "background:var(--track);padding:14px 18px;cursor:default" }, [
    el("div", { class: "code" }, [el("pre", { text: JSON.stringify(args, null, 2) })]),
    el("div", { class: "kv-list", style: "grid-template-columns:1fr;margin-top:10px" },
      facts.map(([k, v]) => el("div", { class: "kv" }, [el("span", { text: k }), el("span", { text: String(v) })]))),
    r.run_id && el("div", { style: "margin-top:12px" }, [
      btn("View run →", { kind: "ghost", sm: true, onClick: () => navigate("#/run/" + r.run_id) }),
    ]),
  ]);
  return el("tr", { hidden: true }, [cell]);
}

// ---- utils -----------------------------------------------------------------
function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); return n; }
function agentLabel(identity) { return (identity || "system").split("@")[0].replace("external:", "ext:"); }
function rawAgent(identity) { return String(identity || "").split("@")[0]; }
function resourceLabel(r) {
  const a = safeParse(r.args_json);
  const raw = a.file_path || a.path || a.command || r.tool || "";
  return String(raw).split(/[\\/]/).slice(-2).join("/") || r.tool || "—";
}
function safeParse(s) { try { return JSON.parse(s); } catch { return {}; } }
function escapeHtml(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

function noProject() {
  return el("div", { class: "card", style: "margin-top:20px" }, [el("div", { class: "bd" }, [
    empty({
      title: "No project yet",
      text: "Run  drydock init  in a git repo, then refresh. Approvals and the audit trail fill in as your agents run.",
      icon: ICONS.ship,
    }),
  ])]);
}
