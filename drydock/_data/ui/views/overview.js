// Overview — Mission Control. The signature page: governance you watch.
// Reference implementation for all other views (component vocabulary + layout rhythm).
import { api } from "../api.js";
import { el, card, stat, pill, badge, btn, empty, skeleton, relTime, clockTime, fmtTokens, ICONS, toast, dispatchModal } from "../ui.js";
import { navigate } from "../router.js";

export async function overviewView(root, { state }) {
  if (!state.project) { root.append(noProject()); return; }

  root.append(el("div", { class: "page-h" }, [
    el("div", {}, [
      el("h2", { class: "t", text: "Mission Control" }),
      el("div", { class: "sub", text: "Everything your agents did — and everything waiting on you." }),
    ]),
    el("div", { class: "actions" }, [
      btn("New ticket", { kind: "ghost", icon: iconSpan(ICONS.plus), onClick: () => navigate("#/work") }),
      btn("Dispatch agent", { kind: "primary", onClick: () => dispatchModal(state, { navigate }) }),
    ]),
  ]));

  const loading = el("div", { class: "stack" }, [skeleton(1), skeleton(3)]);
  root.append(loading);

  let ov;
  try { ov = await api.overview(state.project); }
  catch (e) { loading.replaceWith(empty({ title: "Server not ready", text: e.message })); return; }
  loading.remove();

  const c = ov.counts;
  // ---- KPI row -------------------------------------------------------------
  const kpis = el("div", { class: "grid g-4", style: "margin-bottom:16px" }, [
    stat({ label: "Open tickets", value: c.open_tickets, cap: `${c.ready} ready for pickup` }),
    stat({ label: "Running now", value: c.running, cap: "agents in sandboxes" }),
    stat({ label: "Waiting on you", value: c.pending_asks, cap: "approvals pending", attn: c.pending_asks > 0 }),
    stat({ label: "Decisions today", value: c.audit_today, cap: `${ov.outcomes.deny || 0} denied · ${ov.outcomes.ask || 0} asks` }),
  ]);
  root.append(kpis);

  // ---- main split: governance stream + right column ------------------------
  const main = el("div", { class: "grid g-main", style: "margin-bottom:16px" });

  // decision feed (the signature)
  const feed = el("div", { class: "feed" });
  const decisions = ov.decision_feed || [];
  if (!decisions.length) {
    feed.append(empty({ title: "No activity yet", text: "Dispatch an agent and its decisions stream here." }));
  } else {
    decisions.slice(0, 12).forEach((d) => feed.append(feedRow(d)));
  }
  main.append(card({
    title: "Decision feed", live: true, meta: "every action, checked before it runs",
    link: { text: "Full audit →" }, onLink: () => navigate("#/audit"),
    body: [feed], flush: true,
  }));

  // right column: ask queue + local summary
  const right = el("div", { class: "stack" });
  right.append(askQueueCard(ov.asks, state));
  right.append(localSummaryCard(ov, state));
  main.append(right);
  root.append(main);

  // ---- bottom: work + memory ----------------------------------------------
  const bottom = el("div", { class: "grid g-2" });
  bottom.append(workCard(state));
  bottom.append(memoryCard(ov, state));
  root.append(bottom);
}

// ---- pieces ----------------------------------------------------------------

function feedRow(d) {
  const res = el("span", { class: "res" });
  res.innerHTML = `${escapeHtml(d.action || "")} · <b>${escapeHtml(shortArg(d))}</b>` +
    (d.rule && d.decision !== "allow" ? ` <span class="muted">${escapeHtml(d.rule)}</span>` : "");
  return el("div", { class: "row" }, [
    el("span", { class: "time", text: clockTime(d.ts) }),
    el("span", { class: "agent", text: agentLabel(d.identity) }),
    res,
    badge(d.decision),
  ]);
}

function askQueueCard(asks, state) {
  const body = el("div", {});
  if (!asks || !asks.length) {
    body.append(empty({ title: "Nothing to approve", text: "Agents are running within policy." }));
  } else {
    asks.slice(0, 4).forEach((a) => body.append(askItem(a, state)));
  }
  return card({
    title: "Ask queue", meta: asks && asks.length ? `${asks.length} pending` : "clear",
    link: asks && asks.length ? { text: "All →" } : null, onLink: () => navigate("#/approvals"),
    body: [body], flush: true,
  });
}

function askItem(a, state) {
  const d = a.detail || {};
  const cmd = (d.args_json && safeParse(d.args_json).command) || d.tool || "action";
  const node = el("div", { class: "ask-item" }, [
    el("div", { class: "top" }, [
      el("span", { class: "who", text: agentLabel(d.identity) }),
      pill(d.action || "action", "ask"),
      el("span", { class: "age", text: relTime(a.created_at) }),
    ]),
    el("div", { class: "what", html: `${escapeHtml(d.message || "Needs your approval")} <code>${escapeHtml(String(cmd).slice(0, 60))}</code>` }),
    el("div", { class: "acts" }, [
      btn("Deny", { kind: "danger", sm: true, onClick: () => resolve(a.id, "denied", node) }),
      btn("Approve", { kind: "accent", sm: true, onClick: () => resolve(a.id, "approved_once", node) }),
    ]),
  ]);
  return node;
}

async function resolve(id, resolution, node) {
  try {
    await api.resolveAsk(id, resolution);
    toast(resolution === "denied" ? "Denied" : "Approved", resolution === "denied" ? "err" : "ok");
    node.style.opacity = ".4";
    node.querySelectorAll("button").forEach((b) => (b.disabled = true));
  } catch (e) { toast(e.message, "err"); }
}

function localSummaryCard(ov, state) {
  const rows = [
    ["Agents running", ov.counts.running],
    ["Open tickets", ov.counts.open_tickets],
    ["Audit events today", ov.counts.audit_today],
    ["Allowed / denied / asked", `${ov.outcomes.allow || 0} / ${ov.outcomes.deny || 0} / ${ov.outcomes.ask || 0}`],
  ];
  const list = el("div", { class: "kv-list", style: "grid-template-columns:1fr" },
    rows.map(([k, v]) => el("div", { class: "kv" }, [el("span", { text: k }), el("span", { text: String(v) })])));
  return card({ title: "Local run summary", meta: "today", body: [list] });
}

function workCard(state) {
  const body = el("div", { class: "bd flush" });
  const wrap = card({ title: "Ready for pickup", meta: "scoped tickets an agent can start",
    link: { text: "All tickets →" }, onLink: () => navigate("#/work"), body: [body], flush: true });
  api.tickets(state.project, "ready").then((tks) => {
    if (!tks.length) { body.append(empty({ title: "No tickets ready", text: "Add a plan to make a ticket dispatch-ready." })); return; }
    const tbl = el("table", { class: "tbl" }, [el("tbody", {},
      tks.slice(0, 5).map((t) => el("tr", { onclick: () => navigate(`#/ticket/${t.key}`), style: "cursor:pointer" }, [
        el("td", { class: "mono", text: t.key, style: "width:80px" }),
        el("td", { text: t.title }),
        el("td", { html: `<span class="prio p${t.priority}">P${t.priority}</span>`, style: "width:44px" }),
        el("td", { class: "r", html: '<span class="pill ok">Ready</span>' }),
      ])))]);
    body.append(tbl);
  }).catch(() => body.append(empty({ title: "—" })));
  return wrap;
}

function memoryCard(ov, state) {
  const body = el("div", {});
  const h = ov.handoff;
  if (h) {
    body.append(el("div", { class: "ask-item", style: "border:none;padding-top:0" }, [
      el("div", { class: "top" }, [pill("Active handoff", "navy"), el("span", { class: "age", text: relTime(h.created_at) })]),
      el("div", { class: "what", text: h.summary || h.current_state || "In progress" }),
    ]));
  }
  const decWrap = el("div", { class: "stack", style: "gap:8px" });
  body.append(decWrap);
  api.decisions(state.project).then((ds) => {
    if (!ds.length && !h) { body.append(empty({ title: "No memory yet", text: "Decisions and handoffs will appear here." })); return; }
    ds.slice(0, 3).forEach((d) => decWrap.append(el("div", { style: "padding:8px 0;border-top:1px solid var(--line-2)" }, [
      el("div", { style: "font-size:13px;font-weight:600", text: d.title }),
      el("div", { class: "muted", style: "font-size:12px", text: (d.rationale || "").slice(0, 90) }),
    ])));
  }).catch(() => {});
  return card({ title: "Project memory", meta: "handoff + decisions",
    link: { text: "Open memory →" }, onLink: () => navigate("#/memory"), body: [body] });
}

function noProject() {
  return el("div", { class: "card", style: "margin-top:20px" }, [el("div", { class: "bd" }, [
    empty({
      title: "No project yet",
      text: "Run  drydock init  in a git repo, then refresh. Drydock registers the repo and this dashboard fills in.",
      icon: ICONS.ship,
    }),
  ])]);
}

// ---- utils -----------------------------------------------------------------
function iconSpan(svg) { return el("span", { class: "ic", html: svg, style: "width:15px;height:15px" }); }
function agentLabel(identity) { return (identity || "system").split("@")[0].replace("external:", "ext:"); }
function shortArg(d) {
  const a = safeParse(d.args_json || "{}");
  return String(a.file_path || a.path || a.command || d.tool || "").split(/[\\/]/).slice(-2).join("/") || d.tool || "";
}
function safeParse(s) { try { return JSON.parse(s); } catch { return {}; } }
function escapeHtml(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
