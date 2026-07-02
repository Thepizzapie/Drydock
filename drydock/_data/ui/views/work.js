// Work — the ticket board. Scoped briefs an agent can pick up, and the detail
// view where a ticket becomes a dispatch. PM is first-class here, not a side effect.
import { api } from "../api.js";
import { el, card, stat, pill, btn, empty, skeleton, relTime, ICONS, modal, toast, dispatchModal } from "../ui.js";
import { navigate } from "../router.js";

const FILTERS = [
  { key: null, label: "All" },
  { key: "ready", label: "Ready" },
  { key: "in_progress", label: "In progress" },
  { key: "done", label: "Done" },
];

// status → pill kind (ready→ok, in_progress→info, review→navy, done→mute, open→mute)
function statusPill(status) {
  const k = { ready: "ok", in_progress: "info", review: "navy", done: "mute", open: "mute" }[status] || "mute";
  return pill(statusLabel(status), k);
}
function statusLabel(status) {
  return { ready: "Ready", in_progress: "In progress", review: "Review", done: "Done", open: "Open" }[status] || (status || "—");
}

export async function workView(root, { state }) {
  if (!state.project) { root.append(noProject()); return; }

  let active = null; // current status filter

  root.append(el("div", { class: "page-h" }, [
    el("div", {}, [
      el("h2", { class: "t", text: "Work" }),
      el("div", { class: "sub", text: "Tickets and pickup-ready briefs." }),
    ]),
    el("div", { class: "actions" }, [
      btn("New ticket", { kind: "ghost", icon: iconSpan(ICONS.plus), onClick: () => newTicketModal(state, { onCreated }) }),
    ]),
  ]));

  // KPI strip — counts across every status, regardless of the filter below
  const kpiHost = el("div", { class: "grid g-4", style: "margin-bottom:16px" });
  root.append(kpiHost);

  // segmented status filter
  const seg = el("div", { class: "seg", style: "margin-bottom:16px" });
  const segBtns = FILTERS.map((f) => {
    const b = el("button", { class: active === f.key ? "on" : "", text: f.label, onclick: () => setFilter(f.key) });
    return b;
  });
  segBtns.forEach((b) => seg.append(b));
  root.append(seg);

  const bodyHost = el("div", { class: "card", style: "overflow:hidden" });
  root.append(bodyHost);

  function setFilter(key) {
    active = key;
    segBtns.forEach((b, i) => (b.className = FILTERS[i].key === active ? "on" : ""));
    load();
  }

  async function loadKpis() {
    try {
      const all = await api.tickets(state.project);
      const n = (s) => all.filter((t) => t.status === s).length;
      kpiHost.replaceChildren(
        stat({ label: "Open", value: n("open") }),
        stat({ label: "Ready", value: n("ready"), cap: "dispatch-ready" }),
        stat({ label: "In progress", value: n("in_progress") }),
        stat({ label: "Done", value: n("done") }),
      );
    } catch (_) { kpiHost.replaceChildren(); }
  }

  async function load() {
    bodyHost.replaceChildren(skeleton(5));
    let tickets;
    try { tickets = await api.tickets(state.project, active); }
    catch (e) { bodyHost.replaceChildren(el("div", { class: "bd" }, [empty({ title: "Couldn't load tickets", text: e.message })])); return; }

    if (!tickets.length) {
      bodyHost.replaceChildren(el("div", { class: "bd" }, [emptyForFilter(active)]));
      return;
    }
    bodyHost.replaceChildren(ticketTable(tickets));
  }

  function onCreated(out) {
    loadKpis();
    load();
    const key = out && out.ticket && out.ticket.key;
    if (key) navigate(`#/ticket/${key}`);
  }

  loadKpis();
  await load();
}

function ticketTable(tickets) {
  const rows = tickets.map((t) => el("tr", { style: "cursor:pointer", onclick: () => navigate(`#/ticket/${t.key}`) }, [
    el("td", { class: "mono", text: t.key, style: "width:78px" }),
    el("td", { text: t.title }),
    el("td", { html: `<span class="prio p${t.priority}">P${t.priority}</span>`, style: "width:44px" }),
    el("td", { style: "width:112px" }, [statusPill(t.status)]),
    el("td", { class: "r muted", text: relTime(t.updated_at || t.created_at), style: "width:96px" }),
  ]));
  return el("table", { class: "tbl" }, [
    el("thead", {}, [el("tr", {}, [
      el("th", { text: "Key" }), el("th", { text: "Title" }), el("th", { text: "Priority" }),
      el("th", { text: "Status" }), el("th", { class: "r", text: "Updated" }),
    ])]),
    el("tbody", {}, rows),
  ]);
}

function emptyForFilter(key) {
  const msgs = {
    null: { title: "No tickets yet", text: "Create one above — add plan steps and it arrives scoped, ready for an agent." },
    ready: { title: "Nothing ready for pickup", text: "A ticket becomes ready once every step has scoped files." },
    in_progress: { title: "No tickets in progress", text: "Dispatch an agent to a ready ticket and it moves here." },
    done: { title: "Nothing done yet", text: "Finished tickets land here once an agent wraps them up." },
  };
  const m = msgs[key] || msgs.null;
  return empty({ title: m.title, text: m.text, icon: ICONS.ticket });
}

// New ticket — title, priority, optional description, and an optional plan:
// step rows with scoped files. With steps, the server builds the full plan
// (ticket + pinned plan memory + scoped tasks) so the ticket lands dispatch-ready.
function newTicketModal(state, { onCreated } = {}) {
  const titleIn = el("input", { class: "input", placeholder: "e.g. Add rate limiting to the API" });
  const prioSel = el("select", { class: "input" }, [0, 1, 2, 3].map((p) =>
    el("option", { value: String(p), text: ["P0 · critical", "P1 · high", "P2 · normal", "P3 · low"][p],
      selected: p === 2 ? "selected" : null })));
  const descIn = el("textarea", { class: "textarea", placeholder: "optional — what and why, in plain words" });

  const field = (label, control, hint) => el("label", { style: "display:block;margin-bottom:14px" }, [
    el("div", { style: "font-size:12px;font-weight:600;color:var(--ink-2);margin-bottom:5px", text: label }),
    control,
    hint && el("div", { class: "muted", style: "font-size:11.5px;margin-top:4px", text: hint }),
  ]);

  // plan steps — dynamic rows, each a step title + comma-separated scoped files
  const stepRows = new Set();
  const stepsHost = el("div", { class: "stack", style: "gap:8px" });
  function addStepRow() {
    const stepTitle = el("input", { class: "input", placeholder: `Step ${stepRows.size + 1} — e.g. Add the middleware` });
    const stepFiles = el("input", { class: "input mono", style: "font-size:12px",
      placeholder: "scoped files — src/api.js, src/limits.js" });
    const entry = { stepTitle, stepFiles, row: null };
    const rm = btn("×", { kind: "ghost", sm: true, onClick: () => { stepRows.delete(entry); entry.row.remove(); } });
    rm.setAttribute("aria-label", "Remove step");
    entry.row = el("div", { style: "display:grid;grid-template-columns:1fr 1.2fr auto;gap:8px;align-items:center" },
      [stepTitle, stepFiles, rm]);
    stepRows.add(entry);
    stepsHost.append(entry.row);
  }

  const stepsSection = el("div", { style: "margin-bottom:14px" }, [
    el("div", { style: "font-size:12px;font-weight:600;color:var(--ink-2);margin-bottom:5px", text: "Plan steps" }),
    el("div", { class: "muted", style: "font-size:11.5px;margin-bottom:8px",
      text: "Each step becomes a scoped task an agent can pick up. Leave empty for a simple ticket." }),
    stepsHost,
    el("div", { style: "margin-top:8px" }, [btn("+ Add step", { kind: "ghost", sm: true, onClick: addStepRow })]),
  ]);

  const go = btn("Create ticket", { kind: "primary", onClick: async () => {
    const title = titleIn.value.trim();
    if (!title) { toast("Give the ticket a title", "err"); return; }
    const steps = [...stepRows]
      .map((r) => ({ title: r.stepTitle.value.trim(),
        files: r.stepFiles.value.split(",").map((s) => s.trim()).filter(Boolean) }))
      .filter((s) => s.title);
    go.disabled = true; go.textContent = "Creating…";
    try {
      const out = await api.createTicket(state.project, {
        title, body: descIn.value.trim(), priority: Number(prioSel.value), steps });
      m.close();
      const key = out && out.ticket && out.ticket.key;
      toast(steps.length ? `Created ${key || "ticket"} with a ${steps.length}-step plan` : `Created ${key || "ticket"}`, "ok");
      if (onCreated) onCreated(out);
    } catch (e) { toast(e.message, "err"); go.disabled = false; go.textContent = "Create ticket"; }
  } });

  const m = modal({
    title: "New ticket",
    body: [
      field("Title", titleIn),
      field("Priority", prioSel),
      field("Description", descIn),
      stepsSection,
    ],
    actions: [btn("Cancel", { kind: "ghost", onClick: () => m.close() }), go],
  });
}

export async function ticketView(root, { rest, state }) {
  if (!state.project) { root.append(noProject()); return; }
  const key = rest[0];

  root.append(el("div", { class: "page-h" }, [
    el("div", {}, [
      el("a", { class: "muted", href: "#/work", style: "font-size:12px;font-weight:600", text: "← Work" }),
      el("h2", { class: "t", text: key || "Ticket", style: "margin-top:2px" }),
    ]),
  ]));

  if (!key) { root.append(el("div", { class: "card" }, [el("div", { class: "bd" }, [empty({ title: "No ticket", text: "Pick a ticket from the work board." })])])); return; }

  const host = el("div", {});
  host.append(el("div", { class: "card" }, [skeleton(5)]));
  root.append(host);

  let data;
  try { data = await api.ticket(state.project, key); }
  catch (e) {
    host.replaceChildren(el("div", { class: "card" }, [el("div", { class: "bd" }, [
      empty({ title: "Ticket not found", text: `No ticket ${key} in this project. It may have been renamed or removed.`, icon: ICONS.ticket }),
    ])]));
    return;
  }

  const { ticket, work_items, scopes, readiness } = data;
  if (!ticket) {
    host.replaceChildren(el("div", { class: "card" }, [el("div", { class: "bd" }, [
      empty({ title: "Ticket not found", text: `No ticket ${key} in this project.`, icon: ICONS.ticket }),
    ])]));
    return;
  }

  host.replaceChildren();

  // header row: title + status + readiness + priority
  host.append(card({
    title: ticket.title || ticket.key,
    body: [
      el("div", { class: "row-between", style: "align-items:flex-start" }, [
        el("div", { style: "display:flex;align-items:center;gap:10px" }, [
          statusPill(ticket.status),
          readinessPill(readiness),
          el("span", { html: `<span class="prio p${ticket.priority}">P${ticket.priority}</span>` }),
          el("span", { class: "mono muted", style: "font-size:12px", text: ticket.key }),
        ]),
      ]),
      ticket.body
        ? el("div", { style: "margin-top:14px;white-space:pre-wrap;font-size:13px;line-height:1.6", text: ticket.body })
        : el("div", { class: "muted", style: "margin-top:14px", text: "No brief written yet." }),
    ],
  }));

  // work items — each step with its file scope and a fetchable task brief
  const items = work_items || [];
  const scopeMap = scopes || {};
  const wiBody = el("div", { class: "bd flush" });
  if (!items.length) {
    wiBody.append(empty({ title: "No work items", text: "This ticket hasn't been broken into steps yet." }));
  } else {
    wiBody.append(el("table", { class: "tbl" }, [el("tbody", {}, items.map((w) =>
      workItemRow(w, scopeMap[w.id] || [], state)))]));
  }
  host.append(el("div", { style: "margin-top:16px" }, [card({
    title: "Work items", meta: items.length ? `${items.length} step${items.length === 1 ? "" : "s"}` : "none yet",
    body: [wiBody], flush: true,
  })]));

  // dispatch action if the ticket looks ready to hand to an agent
  if (isDispatchReady(ticket)) {
    host.append(el("div", { style: "margin-top:16px;display:flex;gap:8px" }, [
      btn("Dispatch agent", { kind: "primary", onClick: () => dispatchModal(state, { ticket: ticket.key, navigate }) }),
    ]));
  }
}

// readiness = { ready, has_plan, tasks_total, tasks_scoped }
function readinessPill(r) {
  if (!r) return null;
  if (r.ready) return pill("Dispatch-ready", "ok");
  if (!r.has_plan && (r.tasks_total || 0) === 0) return pill("No plan yet", "mute");
  return pill(`Needs scoping ${r.tasks_scoped || 0}/${r.tasks_total || 0}`, "mute");
}

function workItemRow(w, files, state) {
  const briefBtn = btn("Brief", { kind: "ghost", sm: true, onClick: async () => {
    briefBtn.disabled = true; briefBtn.textContent = "Loading…";
    try {
      const b = await api.brief(state.project, w.id);
      modal({
        title: w.title || w.name || "Task brief",
        body: [el("div", { class: "code", style: "border-radius:10px" }, [
          el("pre", { text: (b && b.rendered) || "No brief available for this task yet." }),
        ])],
      });
    } catch (e) { toast(e.message, "err"); }
    briefBtn.disabled = false; briefBtn.textContent = "Brief";
  } });

  return el("tr", {}, [
    el("td", {}, [
      el("div", { text: w.title || w.name || "—" }),
      el("div", { class: "mono muted",
        style: "font-size:11px;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:460px",
        text: files.length ? files.join(" · ") : "unscoped" }),
    ]),
    el("td", { style: "width:112px" }, [statusPill(w.status)]),
    el("td", { class: "r", style: "width:86px" }, [briefBtn]),
  ]);
}

function isDispatchReady(t) {
  return t.status === "ready" || t.status === "open";
}

function noProject() {
  return el("div", { class: "card", style: "margin-top:20px" }, [el("div", { class: "bd" }, [
    empty({
      title: "No project yet",
      text: "Run  drydock init  in a git repo, then refresh. Tickets and work land here once the project is registered.",
      icon: ICONS.ship,
    }),
  ])]);
}

function iconSpan(svg) { return el("span", { class: "ic", html: svg, style: "width:15px;height:15px" }); }
