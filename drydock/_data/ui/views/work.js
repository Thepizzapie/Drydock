// Work — the ticket board. Scoped briefs an agent can pick up, and the detail
// view where a ticket becomes a dispatch. PM is first-class here, not a side effect.
import { api } from "../api.js";
import { el, card, pill, btn, empty, skeleton, relTime, ICONS, modal, dispatchModal } from "../ui.js";
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
      btn("New ticket", { kind: "ghost", icon: iconSpan(ICONS.plus), onClick: newTicketModal }),
    ]),
  ]));

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
    null: { title: "No tickets yet", text: "Add a plan to your repo and a ticket appears here, ready to pick up." },
    ready: { title: "Nothing ready for pickup", text: "A ticket becomes ready once it has a scoped, dispatch-ready brief." },
    in_progress: { title: "No tickets in progress", text: "Dispatch an agent to a ready ticket and it moves here." },
    done: { title: "Nothing done yet", text: "Finished tickets land here once an agent wraps them up." },
  };
  const m = msgs[key] || msgs.null;
  return empty({ title: m.title, text: m.text, icon: ICONS.ticket });
}

// Tickets aren't created through the API yet — be honest about it instead of
// faking a create that won't stick. They come in via the CLI / MCP.
function newTicketModal() {
  modal({
    title: "New ticket",
    body: [
      el("p", { class: "muted", style: "margin:0 0 12px;line-height:1.55",
        text: "Tickets are created from your repo, not this dashboard yet. Use the drydock CLI or MCP to add one — it shows up here once it lands." }),
      el("div", { class: "code", style: "border-radius:10px" }, [
        el("pre", { text: "drydock ticket new" }),
      ]),
      el("p", { class: "muted", style: "margin:12px 0 0;font-size:12px",
        text: "Prefer the agent path? Ask your MCP client to create a ticket for this project." }),
    ],
    actions: [btn("Got it", { kind: "primary", onClick: () => document.querySelector(".scrim")?.remove() })],
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

  const { ticket, work_items } = data;
  if (!ticket) {
    host.replaceChildren(el("div", { class: "card" }, [el("div", { class: "bd" }, [
      empty({ title: "Ticket not found", text: `No ticket ${key} in this project.`, icon: ICONS.ticket }),
    ])]));
    return;
  }

  host.replaceChildren();

  // header row: title + status + priority
  host.append(card({
    title: ticket.title || ticket.key,
    body: [
      el("div", { class: "row-between", style: "align-items:flex-start" }, [
        el("div", { style: "display:flex;align-items:center;gap:10px" }, [
          statusPill(ticket.status),
          el("span", { html: `<span class="prio p${ticket.priority}">P${ticket.priority}</span>` }),
          el("span", { class: "mono muted", style: "font-size:12px", text: ticket.key }),
        ]),
      ]),
      ticket.body
        ? el("div", { style: "margin-top:14px;white-space:pre-wrap;font-size:13px;line-height:1.6", text: ticket.body })
        : el("div", { class: "muted", style: "margin-top:14px", text: "No brief written yet." }),
    ],
  }));

  // work items
  const items = work_items || [];
  const wiBody = el("div", { class: "bd flush" });
  if (!items.length) {
    wiBody.append(empty({ title: "No work items", text: "This ticket hasn't been broken into steps yet." }));
  } else {
    wiBody.append(el("table", { class: "tbl" }, [el("tbody", {}, items.map((w) =>
      el("tr", {}, [
        el("td", { text: w.title || w.name || "—" }),
        el("td", { class: "r", style: "width:112px" }, [statusPill(w.status)]),
      ])))]));
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
