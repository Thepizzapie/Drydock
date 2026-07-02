// Runs — the live "watch your agent work" experience.
// Two views: runsView (all sessions) and runView (one live transcript + meta).
import { api, streamRun } from "../api.js";
import { el, card, pill, badge, btn, empty, skeleton, relTime, clockTime, fmtTokens, ICONS, toast, modal, dispatchModal } from "../ui.js";
import { navigate } from "../router.js";

// status → pill kind + label. Palette meaning: green=running/healthy, red=error,
// orange=needs a human, mute=idle/terminal.
const STATUS = {
  running: ["ok", "RUNNING"],
  waiting: ["ask", "WAITING"],
  done:    ["mute", "DONE"],
  failed:  ["deny", "FAILED"],
  queued:  ["mute", "QUEUED"],
  killed:  ["mute", "KILLED"],
};
function statusPill(status) {
  const [kind, label] = STATUS[status] || ["mute", String(status || "—").toUpperCase()];
  return pill(label, kind);
}
const isLive = (s) => s === "running" || s === "waiting";

// ---- runsView: the list -----------------------------------------------------

export async function runsView(root, { state }) {
  if (!state.project) { root.append(noProject()); return; }

  const filters = ["All", "Running", "Waiting", "Done"];
  let active = "All";

  root.append(el("div", { class: "page-h" }, [
    el("div", {}, [
      el("h2", { class: "t", text: "Runs" }),
      el("div", { class: "sub", text: "Live agent sessions in isolated sandboxes." }),
    ]),
    el("div", { class: "actions" }, [
      btn("Dispatch agent", { kind: "primary", onClick: () => dispatchModal(state, { navigate }) }),
    ]),
  ]));

  const seg = el("div", { class: "seg", style: "margin-bottom:16px" });
  const body = el("div", {});
  const wrap = card({ title: "Sessions", meta: "newest first", body: [body], flush: true });
  root.append(seg);
  root.append(wrap);

  const loading = skeleton(5);
  body.append(loading);

  let runs;
  try { runs = await api.runs(state.project); }
  catch (e) { loading.replaceWith(empty({ title: "Couldn't load runs", text: e.message })); return; }
  loading.remove();

  filters.forEach((f) => {
    const b = el("button", { class: f === active ? "on" : "", text: f, onclick: () => {
      active = f;
      seg.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x.textContent === f));
      paint();
    } });
    seg.append(b);
  });

  function paint() {
    body.replaceChildren();
    const rows = runs.filter((r) => {
      if (active === "All") return true;
      if (active === "Running") return r.status === "running";
      if (active === "Waiting") return r.status === "waiting";
      if (active === "Done") return r.status === "done";
      return true;
    });
    if (!rows.length) {
      body.append(empty({
        title: active === "All" ? "No runs yet" : `No ${active.toLowerCase()} runs`,
        text: active === "All"
          ? "Dispatch an agent against a ticket and its session appears here — live."
          : "Nothing matches this filter right now.",
        icon: ICONS.runs,
      }));
      return;
    }
    body.append(runsTable(rows));
  }
  paint();
}

function runsTable(runs) {
  const thead = el("thead", {}, [el("tr", {}, [
    el("th", { text: "Agent" }),
    el("th", { text: "Status" }),
    el("th", { text: "Runner" }),
    el("th", { text: "Tier" }),
    el("th", { class: "r", text: "Tokens" }),
    el("th", { class: "r", text: "Started" }),
  ])]);
  const tbody = el("tbody", {}, runs.map((r) => el("tr", {
    onclick: () => navigate("#/run/" + r.id), style: "cursor:pointer",
  }, [
    el("td", {}, [
      el("div", { style: "font-weight:600", text: agentName(r) }),
      r.summary && el("div", { class: "muted", style: "font-size:12px", text: String(r.summary).slice(0, 90) }),
    ]),
    el("td", {}, [statusPill(r.status)]),
    el("td", { class: "mono", text: r.runner || "—" }),
    el("td", { text: tierLabel(r.tier) }),
    el("td", { class: "num", text: fmtTokens((r.tokens_in || 0) + (r.tokens_out || 0)) }),
    el("td", { class: "num", text: relTime(r.started_at) }),
  ])));
  return el("table", { class: "tbl" }, [thead, tbody]);
}

// ---- runView: the live transcript ------------------------------------------

export async function runView(root, { rest, state }) {
  const id = rest[0];
  if (!id) { root.append(empty({ title: "No run selected", text: "Pick a session from the Runs list." })); return; }

  const header = el("div", { class: "page-h" });
  root.append(header);
  const layout = el("div", { class: "grid g-main" });
  root.append(layout);

  const left = el("div", {});
  const right = el("div", { class: "stack" });
  layout.append(left);
  layout.append(right);

  const loading = skeleton(6);
  left.append(loading);

  let data;
  try { data = await api.run(id); }
  catch (e) {
    header.append(el("div", {}, [el("h2", { class: "t", text: "Run " + shortId(id) })]));
    loading.replaceWith(empty({ title: "Couldn't load run", text: e.message }));
    return;
  }
  loading.remove();

  const run = data.run || {};
  const events = (data.events || []).slice();
  const workspace = data.workspace || {};

  // header ------------------------------------------------------------------
  header.replaceChildren(
    el("div", {}, [
      el("h2", { class: "t", text: "Run " + shortId(id) }),
      el("div", { class: "sub", text: subLine(run) }),
    ]),
    el("div", { class: "actions" }, [
      btn("← All runs", { kind: "ghost", onClick: () => navigate("#/runs") }),
    ]),
  );

  // LEFT: transcript --------------------------------------------------------
  const stream = el("div", { class: "stream" });
  if (events.length) events.forEach((ev) => stream.append(evRow(ev)));
  else stream.append(empty({ title: "No events yet", text: "The transcript fills in as the agent works." }));

  const scroller = el("div", { class: "bd flush", style: "max-height:70vh;overflow:auto;padding:4px 18px" }, [stream]);
  const transcriptCard = card({
    title: "Transcript",
    live: isLive(run.status),
    meta: isLive(run.status) ? "streaming" : `${events.length} events`,
    body: [scroller], flush: true,
  });
  left.append(transcriptCard);

  const atBottom = () => scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 40;
  const toBottom = () => { scroller.scrollTop = scroller.scrollHeight; };
  toBottom();

  // RIGHT: pending approval (if waiting) + meta -----------------------------
  const askSlot = el("div", {});
  right.append(askSlot);
  right.append(metaCard(run, workspace, id));

  if (run.status === "waiting") renderPendingAsk(askSlot, run, state, id);

  // LIVE: stream new events -------------------------------------------------
  if (isLive(run.status)) {
    let seen = events.length ? Math.max(...events.map((e) => e.seq ?? 0)) : -1;
    const close = streamRun(id,
      (ev) => {
        if (ev == null) return;
        if (ev.seq != null && ev.seq <= seen) return; // de-dupe replays
        if (ev.seq != null) seen = ev.seq;
        if (!stream.querySelector(".ev")) stream.replaceChildren(); // drop the placeholder
        const stick = atBottom();
        stream.append(evRow(ev));
        if (stick) toBottom();
      },
      (end) => {
        const finalStatus = (end && end.status) || "done";
        run.status = finalStatus;
        transcriptCard.querySelector(".live")?.remove();
        const meta = transcriptCard.querySelector(".hd .meta");
        if (meta) meta.textContent = "ended";
        // refresh the right-column status pill + clear any stale ask
        right.replaceChildren(el("div", {}), metaCard(run, workspace, id));
        toast("Run " + finalStatus, finalStatus === "failed" ? "err" : "ok");
      });
    onLeave(root, close);
  }
}

// ---- transcript rows -------------------------------------------------------

function evRow(ev) {
  const gutter = el("span", { class: "gutter", text: glyph(ev.type) });
  const bodyEl = el("div", { class: "body" });
  const p = ev.payload || {};
  let toolClass = "";

  if (ev.type === "message") {
    bodyEl.append(el("div", { class: "h", text: "assistant" }));
    bodyEl.append(el("div", { class: "txt", text: p.text || p.raw || "" }));
  } else if (ev.type === "tool_call") {
    toolClass = " tool";
    bodyEl.append(el("div", { class: "h", text: p.name || "tool" }));
    const args = p.args !== undefined ? p.args : p.input;
    if (args !== undefined) bodyEl.append(el("div", { class: "txt mono", text: pretty(args) }));
  } else if (ev.type === "tool_result") {
    toolClass = " tool";
    const ok = p.ok !== false;
    const head = el("div", { class: "h" }, [
      "result",
      p.ok === false && el("span", { style: "margin-left:8px" }, [pill("error", "deny")]),
    ]);
    bodyEl.append(head);
    const out = ok ? (p.output ?? "") : (p.error ?? p.output ?? "");
    bodyEl.append(el("div", { class: "txt mono", text: pretty(out) }));
  } else if (ev.type === "decision") {
    const head = el("div", { class: "h" }, [
      el("span", { class: "mono", text: p.tool || "action" }),
      el("span", { style: "margin-left:8px" }, [badge(p.decision || "ask")]),
    ]);
    bodyEl.append(head);
    if (p.rule) bodyEl.append(el("div", { class: "txt muted", text: p.rule }));
  } else if (ev.type === "status") {
    bodyEl.append(el("div", { class: "txt muted", text: p.status || "" }));
  } else {
    bodyEl.append(el("div", { class: "txt", text: pretty(p) }));
  }

  if (ev.ts) bodyEl.append(el("div", { class: "muted", style: "font-size:10.5px;margin-top:2px;font-family:var(--mono)", text: clockTime(ev.ts) }));
  return el("div", { class: "ev" + toolClass }, [gutter, bodyEl]);
}

function glyph(type) {
  return type === "message" ? "›"
    : type === "tool_call" ? "»"
    : type === "tool_result" ? "«"
    : type === "decision" ? "◆"
    : "·";
}

// ---- right column ----------------------------------------------------------

function metaCard(run, workspace, id) {
  const rows = [
    ["Status", null, statusPill(run.status)],
    ["Runner", run.runner || "—", null],
    ["Tier", tierLabel(run.tier), null],
    ["Tokens in", fmtTokens(run.tokens_in), null],
    ["Tokens out", fmtTokens(run.tokens_out), null],
    ["Cost", fmtCost(run.cost_cents), null],
    ["Workspace", null, el("span", { class: "mono", style: "font-size:11px;text-align:right;word-break:break-all", text: workspacePath(workspace, run) })],
    ["Started", relTime(run.started_at), null],
  ];
  const list = el("div", { class: "kv-list", style: "grid-template-columns:1fr" },
    rows.map(([k, v, node]) => el("div", { class: "kv" }, [
      el("span", { text: k }),
      node || el("span", { text: v == null ? "—" : String(v) }),
    ])));

  const ident = el("div", { class: "ask-item", style: "border:none;padding:0 0 12px" }, [
    el("div", { class: "top" }, [
      el("span", { class: "who", text: agentName(run) }),
      statusPill(run.status),
    ]),
    run.ticket_id && el("div", { class: "muted", style: "font-size:12px;margin-top:4px", text: "Ticket " + run.ticket_id }),
  ]);

  const diffBtn = btn("View diff", { kind: "ghost", icon: iconSpan(ICONS.diff), onClick: () => openDiff(id) });

  return card({
    title: "Run details",
    body: [ident, list, el("div", { style: "margin-top:14px" }, [diffBtn])],
  });
}

async function openDiff(id) {
  const holder = el("div", {}, [skeleton(4)]);
  const m = modal({ title: "Working tree diff", body: [holder] });
  try {
    const diff = await api.runDiff(id);
    const text = typeof diff === "string" ? diff : (diff && diff.diff) || "";
    holder.replaceChildren(text.trim() ? diffBlock(text) : empty({ title: "No changes", text: "This run hasn't modified any files." }));
  } catch (e) {
    holder.replaceChildren(empty({ title: "Couldn't load diff", text: e.message }));
  }
  return m;
}

function diffBlock(text) {
  const pre = el("pre", {});
  text.split("\n").forEach((line, i) => {
    let cls = "";
    if (line.startsWith("@@")) cls = "hunk";
    else if (line.startsWith("+") && !line.startsWith("+++")) cls = "add";
    else if (line.startsWith("-") && !line.startsWith("---")) cls = "del";
    if (i) pre.append(document.createTextNode("\n"));
    pre.append(cls ? el("span", { class: cls, text: line }) : document.createTextNode(line));
  });
  return el("div", { class: "code diff" }, [pre]);
}

// ---- pending approval (waiting runs) ---------------------------------------

async function renderPendingAsk(slot, run, state, runId) {
  let asks;
  try { asks = await api.asks(state.project); } catch (_) { return; }
  const ask = (asks || []).find((a) => a.run_id === runId || a.run_id === run.id);
  if (!ask) return;
  const d = ask.detail || {};
  const cmd = (d.args_json && safeParse(d.args_json).command) || d.tool || "action";

  const node = el("div", { class: "glass", style: "margin-bottom:16px" }, [
    el("div", { class: "k", text: "WAITING ON YOU" }),
    el("h3", { text: d.message || "This agent needs your approval" }),
    el("div", { class: "kv" }, [el("span", { text: d.tool || "tool" }), el("span", { text: String(cmd).slice(0, 60) })]),
    el("div", { class: "sub", style: "margin-top:8px", text: "Approving lets the run continue; denying blocks this one action." }),
    el("div", { class: "acts" }, [
      btn("Deny", { kind: "ghost", onClick: () => resolveAsk(ask.id, "denied", slot) }),
      btn("Approve once", { kind: "accent", onClick: () => resolveAsk(ask.id, "approved_once", slot) }),
    ]),
  ]);
  slot.replaceChildren(node);
}

async function resolveAsk(id, resolution, slot) {
  try {
    await api.resolveAsk(id, resolution);
    toast(resolution === "denied" ? "Denied" : "Approved", resolution === "denied" ? "err" : "ok");
    slot.replaceChildren(); // stream continues; the transcript will show what happens next
  } catch (e) { toast(e.message, "err"); }
}

// ---- shared ----------------------------------------------------------------

function noProject() {
  return el("div", { class: "card", style: "margin-top:20px" }, [el("div", { class: "bd" }, [
    empty({
      title: "No project yet",
      text: "Run  drydock init  in a git repo, then refresh. Runs appear here once an agent is dispatched.",
      icon: ICONS.ship,
    }),
  ])]);
}

// Close the SSE stream the moment the user leaves this view (router swaps the DOM
// on hashchange; there is no unmount hook, so we hook the same event).
function onLeave(root, close) {
  const handler = () => { close(); window.removeEventListener("hashchange", handler); };
  window.addEventListener("hashchange", handler);
  // safety net: if the view node is torn down some other way, still close.
  const obs = new MutationObserver(() => {
    if (!root.isConnected) { close(); obs.disconnect(); window.removeEventListener("hashchange", handler); }
  });
  if (root.parentNode) obs.observe(root.parentNode, { childList: true });
}

function iconSpan(svg) { return el("span", { class: "ic", html: svg, style: "width:15px;height:15px" }); }
function agentName(r) { return (r.agent_id || "agent").split("@")[0].replace("external:", "ext:"); }
function tierLabel(t) { return t == null ? "—" : "Tier " + t; }
function shortId(id) { return String(id || "").slice(0, 8); }
function subLine(run) {
  const parts = [agentName(run)];
  if (run.ticket_id) parts.push("ticket " + run.ticket_id);
  return parts.join(" · ");
}
function workspacePath(ws, run) { return ws.path || ws.root || run.workspace_id || "—"; }
function fmtCost(cents) {
  if (cents == null) return "—";
  return "$" + (cents / 100).toFixed(2);
}
function pretty(v) {
  if (v == null) return "";
  if (typeof v === "string") return v;
  try { return JSON.stringify(v, null, 2); } catch { return String(v); }
}
function safeParse(s) { try { return JSON.parse(s); } catch { return {}; } }
