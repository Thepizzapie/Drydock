// Agents — one page: the registry of who can act, and the compiled policy that
// says exactly what each one is allowed to do. Agents are authored as Markdown;
// the detail pane shows how that Markdown resolves to allow / deny / ask.
import { api } from "../api.js";
import { el, clear, card, pill, badge, btn, empty, skeleton, modal, dispatchModal, agentAuthorModal, clickable, ICONS } from "../ui.js";
import { navigate, render } from "../router.js";

export async function agentsView(root, { params, state }) {
  if (!state.project) { root.append(noProject()); return; }

  root.append(el("div", { class: "page-h" }, [
    el("div", {}, [
      el("h2", { class: "t", text: "Agents" }),
      el("div", { class: "sub", text: "Who can act — and exactly what they're allowed to do." }),
    ]),
    el("div", { class: "actions" }, [
      btn("New agent", { kind: "ghost", icon: iconSpan(ICONS.plus),
        onClick: () => agentAuthorModal(state, { onSaved: (row) => { location.hash = "#/agents?agent=" + encodeURIComponent(row.name); render(); } }) }),
      btn("Dispatch agent", { kind: "primary", onClick: () => dispatchModal(state, { navigate }) }),
    ]),
  ]));

  const loading = el("div", { class: "stack" }, [skeleton(3)]);
  root.append(loading);

  let agents;
  try { agents = await api.agents(state.project); }
  catch (e) { loading.replaceWith(empty({ title: "Couldn't load agents", text: e.message })); return; }
  loading.remove();

  if (!agents || !agents.length) {
    root.append(el("div", { class: "card" }, [el("div", { class: "bd" }, [
      empty({
        title: "No agents yet",
        text: "Build one with “New agent” above — pick a cloud or local model, grant it tools, and set what it's allowed to do. Or drop a Markdown file in .drydock/agents/.",
        icon: ICONS.agents,
      }),
    ])]));
    return;
  }

  // ---- master-detail: registry list left, compiled policy + spec right ------
  let selected = agents.find((a) => a.name === params.agent) || agents[0];

  const rows = new Map(); // name -> list row node
  const listFeed = el("div", { class: "feed" });
  for (const a of agents) {
    const row = listRow(a, () => select(a.name));
    rows.set(a.name, row);
    listFeed.append(row);
  }

  const detail = el("div", { class: "stack" });

  function select(name) {
    selected = agents.find((a) => a.name === name) || agents[0];
    for (const [n, node] of rows) markActive(node, n === selected.name);
    clear(detail);
    detail.append(detailHeader(selected, state), policyCard(selected), specCard(selected));
    // keep the URL shareable without forcing a full re-render
    history.replaceState(null, "", "#/agents?agent=" + encodeURIComponent(selected.name));
  }

  root.append(el("div", {
    class: "grid",
    style: "grid-template-columns:340px minmax(0,1fr);gap:16px;align-items:start",
  }, [
    card({
      title: "Registry",
      meta: agents.length === 1 ? "1 agent" : `${agents.length} agents`,
      body: [listFeed],
      flush: true,
    }),
    detail,
  ]));

  select(selected.name);
}

// ---- registry list ----------------------------------------------------------

function listRow(a, onSelect) {
  const def = a.definition || {};
  const defaultDeny = (def.permissions || {}).default === "deny";

  const row = el("div", { class: "row", style: "grid-template-columns:1fr;cursor:pointer" }, [
    el("div", { style: "min-width:0" }, [
      el("div", { style: "display:flex;align-items:center;gap:8px;min-width:0" }, [
        el("span", {
          class: "mono",
          style: "font-weight:650;font-size:13px;color:var(--navy);overflow:hidden;text-overflow:ellipsis;white-space:nowrap",
          text: a.name,
        }),
        a.version != null && pill("v" + String(a.version), "navy"),
        defaultDeny && el("span", { style: "margin-left:auto" }, [pill("Default deny", "deny")]),
      ]),
      a.description && el("div", {
        class: "muted",
        style: "font-size:12px;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap",
        text: a.description,
      }),
    ]),
  ]);
  return clickable(row, onSelect);
}

function markActive(node, on) {
  node.style.background = on ? "var(--line-2)" : "";
  node.style.boxShadow = on ? "inset 3px 0 0 var(--navy)" : "";
  if (on) node.setAttribute("aria-current", "true");
  else node.removeAttribute("aria-current");
}

// ---- detail pane ------------------------------------------------------------

function detailHeader(a, state) {
  const tools = Array.isArray(a.tools) ? a.tools : [];

  const kids = [
    el("div", { class: "row-between" }, [
      el("div", { style: "display:flex;align-items:center;gap:10px;min-width:0;flex-wrap:wrap" }, [
        el("span", { class: "mono", style: "font-weight:700;font-size:16px;color:var(--navy)", text: a.name }),
        a.version != null && pill("v" + String(a.version), "navy"),
        a.model && pill(a.model, "mute"),
      ]),
      el("div", { style: "display:flex;gap:8px" }, [
        btn("Edit", { kind: "ghost", sm: true,
          onClick: () => agentAuthorModal(state, { existing: a, onSaved: () => render() }) }),
        btn("Dispatch", { kind: "primary", sm: true, onClick: () => dispatchModal(state, { navigate }) }),
      ]),
    ]),
  ];

  if (a.description) {
    kids.push(el("div", { style: "font-size:12.5px;color:var(--ink-2);line-height:1.5;margin-top:8px", text: a.description }));
  }
  if (tools.length) {
    kids.push(el("div", { style: "display:flex;flex-wrap:wrap;gap:6px;margin-top:10px" },
      tools.map((t) => pill(t, "mute"))));
  }

  return el("div", { class: "card" }, [el("div", { class: "bd" }, kids)]);
}

// The signature: how the Markdown compiles to allow / deny / ask, rule by rule,
// ending with the honest default.
function policyCard(a) {
  const def = a.definition || {};
  const perms = def.permissions || {};
  const rules = Array.isArray(perms.rules) ? perms.rules : [];

  const rowsWrap = el("div", { class: "feed" });

  if (!rules.length) {
    rowsWrap.append(el("div", { class: "row", style: "grid-template-columns:1fr auto" }, [
      el("span", { class: "muted", style: "font-size:12.5px", text: "No explicit rules — only the default applies." }),
    ]));
  } else {
    rules.forEach((r) => rowsWrap.append(policyRow(r)));
  }

  // final catch-all row — the honest default
  const dflt = perms.default === "allow" ? "allow" : perms.default === "ask" ? "ask" : "deny";
  rowsWrap.append(el("div", { class: "row", style: "grid-template-columns:1fr auto;background:var(--line-2)" }, [
    el("span", { class: "mono", style: "font-size:12px;color:var(--ink-2)", text: "* everything else" }),
    badge(dflt),
  ]));

  return card({
    title: "Compiled policy",
    meta: "how the Markdown resolves to allow / deny / ask",
    body: [rowsWrap],
    flush: true,
  });
}

function policyRow(r) {
  const action = r.action || r.tool || "*";
  const scope = r.scope || r.match || "";
  const decision = r.decision === "allow" ? "allow" : r.decision === "ask" ? "ask" : r.decision === "deny" ? "deny" : "ask";

  const left = el("div", { style: "min-width:0;display:flex;flex-direction:column;gap:2px" }, [
    el("span", { class: "mono", style: "font-size:12.5px;color:var(--ink);font-weight:600", text: action }),
    scope && el("span", {
      class: "mono",
      style: "font-size:11.5px;color:var(--ink-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap",
      text: scope,
    }),
  ]);

  return el("div", { class: "row", style: "grid-template-columns:1fr auto" }, [
    left,
    badge(decision),
  ]);
}

function specCard(a) {
  const def = a.definition || {};
  const perms = def.permissions || {};
  const tools = Array.isArray(a.tools) ? a.tools : [];

  const rows = [
    ["name", a.name],
    ["model", a.model || "—"],
    ["version", a.version != null ? String(a.version) : "—"],
    ["tools", tools.length ? tools.join(", ") : "—"],
    ["permissions.default", perms.default || "—"],
  ];

  const kv = el("div", { class: "kv-list", style: "grid-template-columns:1fr" },
    rows.map(([k, v]) => el("div", { class: "kv" }, [
      el("span", { text: k }),
      el("span", { text: v }),
    ])));

  const kids = [kv];

  // raw source (frontmatter markdown / compiled yaml), escaped, mono
  const src = a.definition_md || a.policy_yaml;
  if (src) {
    kids.push(el("div", {
      style: "font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);font-weight:700;margin:16px 0 8px",
      text: a.definition_md ? "Source (agent.md)" : "Compiled policy (yaml)",
    }));
    kids.push(el("div", { class: "code" }, [el("pre", { text: String(src) })]));
  }

  return card({ title: "Spec", meta: "read-only", body: kids });
}

// ---- shared -----------------------------------------------------------------

function noProject() {
  return el("div", { class: "card", style: "margin-top:20px" }, [el("div", { class: "bd" }, [
    empty({
      title: "No project yet",
      text: "Run  drydock init  in a git repo, then refresh. Agents you register show up here.",
      icon: ICONS.ship,
    }),
  ])]);
}

function iconSpan(svg) { return el("span", { class: "ic", html: svg, style: "width:15px;height:15px" }); }

// Legacy alias — the router maps both #/agents and #/studio here now.
export const studioView = agentsView;
