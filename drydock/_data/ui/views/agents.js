// Agents + Studio — the registry of who can act, and exactly what they're allowed to do.
// Agents are authored as Markdown; the Studio shows how that Markdown compiles to allow/deny/ask.
import { api } from "../api.js";
import { el, card, pill, badge, btn, empty, skeleton, modal, dispatchModal, ICONS } from "../ui.js";
import { navigate } from "../router.js";

let _state; // captured per render so card actions can reach the current project + tiers

// ---- Agents: the registry ---------------------------------------------------

export async function agentsView(root, { state }) {
  if (!state.project) { root.append(noProject()); return; }
  _state = state;

  root.append(el("div", { class: "page-h" }, [
    el("div", {}, [
      el("h2", { class: "t", text: "Agents" }),
      el("div", { class: "sub", text: "The registry of who can act and what they're allowed to do." }),
    ]),
    el("div", { class: "actions" }, [
      btn("New agent", { kind: "ghost", icon: iconSpan(ICONS.plus), onClick: newAgentModal }),
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
        title: "No agents registered",
        text: "Author an agent as a Markdown file, then register it with  drydock agent add <file>.md",
        icon: ICONS.agents,
      }),
    ])]));
    return;
  }

  const grid = el("div", { class: "grid g-3" }, agents.map(agentCard));
  root.append(grid);
}

function agentCard(a) {
  const def = a.definition || {};
  const perms = def.permissions || {};
  const tools = Array.isArray(a.tools) ? a.tools : [];
  const defaultDeny = perms.default === "deny";

  const head = el("div", { class: "row-between", style: "margin-bottom:8px" }, [
    el("span", { class: "mono", style: "font-weight:700;font-size:14px;color:var(--navy)", text: a.name }),
    a.version && pill("v" + String(a.version), "navy"),
  ]);

  const kids = [head];

  if (a.description) {
    kids.push(el("div", { style: "font-size:12.5px;color:var(--ink-2);line-height:1.5;margin-bottom:10px", text: a.description }));
  }

  kids.push(el("div", { class: "kv-list", style: "grid-template-columns:1fr;margin-bottom:10px" }, [
    el("div", { class: "kv" }, [el("span", { text: "Model" }), el("span", { text: a.model || "—" })]),
  ]));

  if (tools.length) {
    kids.push(el("div", { style: "display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px" },
      tools.slice(0, 6).map((t) => pill(t, "mute")).concat(
        tools.length > 6 ? [pill("+" + (tools.length - 6), "mute")] : [])));
  }

  kids.push(el("div", { class: "row-between" }, [
    defaultDeny ? pill("Default deny", "deny") : pill("No default policy", "mute"),
    el("div", { style: "display:flex;gap:8px" }, [
      btn("Studio", { kind: "ghost", sm: true, onClick: () => navigate("#/studio?agent=" + encodeURIComponent(a.name)) }),
      btn("Dispatch", { kind: "primary", sm: true, onClick: () => dispatchModal(_state, { navigate }) }),
    ]),
  ]));

  return el("div", { class: "card" }, [el("div", { class: "bd" }, kids)]);
}

function newAgentModal() {
  modal({
    title: "New agent",
    body: [
      el("p", { style: "margin:0 0 12px;font-size:13px;color:var(--ink-2);line-height:1.55",
        text: "Agents aren't clicked into existence — they're authored as Markdown files. The frontmatter declares the model, tools, and permission rules; the body is the system prompt." }),
      el("p", { style: "margin:0 0 10px;font-size:13px;color:var(--ink-2);line-height:1.55",
        text: "Write the file, then register it locally:" }),
      el("div", { class: "code" }, [el("pre", { text: "drydock agent add path/to/agent.md" })]),
      el("p", { style: "margin:12px 0 0;font-size:12.5px;color:var(--ink-3);line-height:1.5",
        text: "Drydock parses the frontmatter, compiles the permissions to allow/deny/ask rules, and versions it. Open the Studio to see exactly what it's permitted to do." }),
    ],
    actions: [
      btn("Got it", { kind: "primary", onClick: () => document.querySelector(".scrim")?.remove() }),
    ],
  });
}

// ---- Studio: the spec inspector --------------------------------------------

export async function studioView(root, { params, state }) {
  if (!state.project) { root.append(noProject()); return; }

  root.append(el("div", { class: "page-h" }, [
    el("div", {}, [
      el("h2", { class: "t", text: "Agent Studio" }),
      el("div", { class: "sub", text: "Author agents as Markdown. See exactly what they're permitted to do." }),
    ]),
    el("div", { class: "actions", id: "studioPicker" }),
  ]));

  const loading = el("div", { class: "stack" }, [skeleton(4)]);
  root.append(loading);

  let agents;
  try { agents = await api.agents(state.project); }
  catch (e) { loading.replaceWith(empty({ title: "Couldn't load agents", text: e.message })); return; }
  loading.remove();

  if (!agents || !agents.length) {
    root.append(el("div", { class: "card" }, [el("div", { class: "bd" }, [
      empty({
        title: "No agents to inspect",
        text: "Register an agent with  drydock agent add <file>.md  and it appears here.",
        icon: ICONS.studio,
      }),
    ])]));
    return;
  }

  const selected = agents.find((a) => a.name === params.agent) || agents[0];

  // agent picker in the header actions slot
  const picker = document.getElementById("studioPicker");
  if (picker) {
    const sel = el("select", { class: "input", style: "width:auto;padding:6px 10px;font-size:12.5px",
      onchange: (e) => navigate("#/studio?agent=" + encodeURIComponent(e.target.value)) },
      agents.map((a) => el("option", { value: a.name, text: a.name, selected: a.name === selected.name ? "selected" : null })));
    picker.append(sel);
  }

  const body = el("div", { class: "grid g-main" });
  root.append(body);
  body.append(specPanel(selected));
  body.append(policyPanel(selected));
}

function specPanel(a) {
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

  // raw source (frontmatter markdown / policy yaml), escaped, mono
  const src = a.definition_md || a.policy_yaml;
  if (src) {
    kids.push(el("div", { style: "font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);font-weight:700;margin:16px 0 8px",
      text: a.definition_md ? "Source (agent.md)" : "Compiled policy (yaml)" }));
    kids.push(el("div", { class: "code" }, [el("pre", { text: String(src) })]));
  }

  return card({ title: "Spec", meta: "read-only", body: kids });
}

function policyPanel(a) {
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
    scope && el("span", { class: "mono", style: "font-size:11.5px;color:var(--ink-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap", text: scope }),
  ]);

  return el("div", { class: "row", style: "grid-template-columns:1fr auto" }, [
    left,
    badge(decision),
  ]);
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
