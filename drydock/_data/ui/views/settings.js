// Settings — local config + environment. Also the first-run reference:
// everything runs on this machine, nothing leaves. Keep it clean and reassuring.
import { api } from "../api.js";
import { el, card, pill, btn, empty, skeleton, clear, copyBtn, toast, projectModal, ICONS } from "../ui.js";

export async function settingsView(root, { state }) {
  root.append(el("div", { class: "page-h" }, [
    el("div", {}, [
      el("h2", { class: "t", text: "Settings" }),
      el("div", { class: "sub", text: "Everything runs on this machine. Nothing leaves." }),
    ]),
  ]));

  const loading = el("div", { class: "stack" }, [skeleton(2), skeleton(3)]);
  root.append(loading);

  let doc, tiers;
  try {
    [doc, tiers] = await Promise.all([api.doctor(), api.tiers()]);
  } catch (e) {
    loading.replaceWith(empty({ title: "Couldn't read local config", text: e.message }));
    return;
  }
  loading.remove();

  const stack = el("div", { class: "stack" });
  root.append(stack);

  stack.append(tierSection(doc, tiers));
  stack.append(localModelsSection());
  stack.append(envSection(doc));
  stack.append(mcpSection());
  stack.append(integrationsSection(state));
  stack.append(projectsSection(state));
}

// ---- Local models -----------------------------------------------------------

function localModelsSection() {
  const body = el("div", {});
  body.append(skeleton(2));
  const wrap = card({ title: "Local models", meta: "run agents on your own hardware", body: [body] });

  api.models().then((cat) => {
    clear(body);
    const local = cat.local || { available: false, models: [], endpoint: "" };
    body.append(el("p", {
      class: "muted", style: "margin:0 0 14px;line-height:1.55;font-size:12.5px",
      text: "Point an agent at a local model and it runs offline and free — same sandbox, same policy, same tools. Drydock speaks the OpenAI-compatible API (Ollama, LM Studio, vLLM, …).",
    }));
    body.append(el("div", { class: "kv-list", style: "grid-template-columns:1fr" }, [
      el("div", { class: "kv" }, [el("span", { text: "Endpoint" }), el("span", { class: "mono", text: local.endpoint || "—" })]),
      el("div", { class: "kv" }, [el("span", { text: "Status" }),
        local.available ? pill("connected", "ok") : pill("not detected", "mute")]),
    ]));
    if (local.available && local.models.length) {
      body.append(el("div", { style: "display:flex;flex-wrap:wrap;gap:6px;margin-top:12px" },
        local.models.map((m) => pill(m.label, "info"))));
    } else {
      body.append(el("div", { class: "muted", style: "font-size:11.5px;margin-top:10px",
        text: "No local server found. Start Ollama (ollama serve) or set DRYDOCK_OPENAI_BASE to your server, then reload." }));
    }
    if ((cat.cloud || []).length) {
      body.append(el("div", { style: "font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);margin:16px 0 8px", text: "Cloud models" }));
      body.append(el("div", { style: "display:flex;flex-wrap:wrap;gap:6px" },
        cat.cloud.map((m) => pill(m.label, "mute"))));
    }
  }).catch((e) => { clear(body); body.append(empty({ title: "Couldn't detect models", text: e.message })); });

  return wrap;
}

// ---- Isolation tier ---------------------------------------------------------

const TIERS = [
  { id: 0, name: "Tier 0", label: "Policy-only", desc: "Policy-grade — not a VM boundary.", need: () => true },
  { id: 1, name: "Tier 1", label: "WSL2", desc: "WSL2 VM boundary, Windows drives unmounted.", need: (d) => !!d.wsl },
  { id: 2, name: "Tier 2", label: "Docker", desc: "Docker container.", need: (d) => !!d.docker },
];

function tierSection(doc, tiers) {
  const rec = pickRecommended(doc, tiers);

  const cards = el("div", { class: "grid g-3" }, TIERS.map((t) => {
    const available = t.need(doc);
    const isRec = t.id === rec;

    const head = el("div", { class: "row-between", style: "margin-bottom:8px" }, [
      el("span", { style: "font-weight:700;font-size:14px;color:var(--navy)", text: t.name + " · " + t.label }),
      isRec ? pill("Recommended", "ask") : (available ? pill("Available", "ok") : pill("Not available", "mute")),
    ]);

    return el("div", { class: "card", style: isRec ? "border-color:var(--mist-gray)" : null }, [
      el("div", { class: "bd" }, [
        head,
        el("div", { style: "font-size:12.5px;color:var(--ink-2);line-height:1.5", text: t.desc }),
      ]),
    ]);
  }));

  return card({
    title: "Isolation tier",
    meta: "where an agent's shell actually runs",
    body: [cards],
  });
}

function pickRecommended(doc, tiers) {
  if (doc && Number.isInteger(doc.recommended_tier)) return doc.recommended_tier;
  if (tiers && Number.isInteger(tiers.recommended)) return tiers.recommended;
  if (doc && doc.docker) return 2;
  if (doc && doc.wsl) return 1;
  return 0;
}

// ---- Environment ------------------------------------------------------------

function envSection(doc) {
  const boolPill = (v) => v ? pill("✓", "ok") : pill("—", "mute");

  const rows = [
    ["Data home", monoVal(doc.home)],
    ["Database", monoVal(doc.db)],
    ["Git", boolPill(doc.git)],
    ["WSL2", boolPill(doc.wsl)],
    ["Docker", boolPill(doc.docker)],
    ["Embeddings backend", monoVal(doc.embeddings || "—")],
    ["Vector store", boolPill(doc.vectors)],
  ];

  const list = el("div", { class: "kv-list", style: "grid-template-columns:1fr" },
    rows.map(([k, v]) => el("div", { class: "kv" }, [
      el("span", { text: k }),
      valNode(v),
    ])));

  return card({
    title: "Environment",
    meta: "detected on this machine",
    body: [list],
  });
}

function monoVal(s) { return { mono: String(s == null ? "—" : s) }; }
function valNode(v) {
  if (v && v.nodeType) return v;
  if (v && typeof v === "object" && "mono" in v) return el("span", { class: "mono", text: v.mono });
  return el("span", { text: String(v) });
}

// ---- MCP ----------------------------------------------------------------------

function mcpSection() {
  const body = el("div", {});
  body.append(skeleton(3));
  const wrap = card({ title: "MCP", meta: "plug your agent client into Drydock", body: [body] });

  api.mcpInfo().then((info) => {
    clear(body);
    body.append(el("p", {
      class: "muted", style: "margin:0 0 14px;line-height:1.55;font-size:12.5px",
      text: "Any MCP client — Claude Code, Codex, Cursor — gets Drydock's full PM plane and can dispatch sandboxed runs.",
    }));
    body.append(cmdRow("Claude Code", info.command));
    body.append(cmdRow("Codex", info.codex));
    if (info.note) {
      body.append(el("div", { class: "muted", style: "font-size:11.5px;margin-top:2px;line-height:1.5", text: info.note }));
    }
  }).catch((e) => {
    clear(body);
    body.append(empty({ title: "Couldn't load MCP setup", text: e.message }));
  });

  return wrap;
}

function cmdRow(label, command) {
  return el("div", { style: "margin-bottom:14px" }, [
    el("div", { class: "row-between", style: "margin-bottom:6px" }, [
      el("span", { class: "muted", style: "font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase", text: label }),
      copyBtn(command || ""),
    ]),
    el("div", { class: "code" }, [el("pre", { text: command || "—" })]),
  ]);
}

// ---- Integrations -------------------------------------------------------------

function integrationsSection(state) {
  const result = el("div", {});

  const go = btn("Install hooks into this repo", { kind: "primary", onClick: async () => {
    go.disabled = true;
    const prev = go.textContent;
    go.textContent = "Installing…";
    try {
      const out = await api.installHooks(state.project);
      toast("Hooks installed", "ok");
      clear(result);
      result.append(el("div", { style: "margin-top:14px" }, [
        el("div", { class: "kv-list", style: "grid-template-columns:1fr" }, [
          el("div", { class: "kv" }, [
            el("span", { text: "Settings written" }),
            el("span", { class: "mono", text: out.settings || "—" }),
          ]),
        ]),
        el("div", { style: "display:flex;flex-wrap:wrap;gap:6px;margin-top:10px" },
          (out.events || []).map((ev) => pill(ev, "navy"))),
      ]));
    } catch (e) {
      toast(e.message, "err");
    } finally {
      go.disabled = !state.project;
      go.textContent = prev;
    }
  } });

  const kids = [
    el("p", {
      class: "muted", style: "margin:0 0 14px;line-height:1.55;font-size:12.5px",
      text: "Route external agent sessions in this repo into Drydock's audit trail and approvals.",
    }),
    el("div", {}, [go]),
  ];
  if (!state.project) {
    go.disabled = true;
    kids.push(el("div", { class: "muted", style: "font-size:11.5px;margin-top:8px", text: "Register a project first — hooks install into its repo." }));
  }
  kids.push(result);

  return card({
    title: "Integrations",
    meta: "hooks for external agents",
    body: kids,
  });
}

// ---- Projects ---------------------------------------------------------------

function projectsSection(state) {
  const projects = (state && state.projects) || [];
  const body = el("div", { class: "bd flush" });
  const wrap = card({
    title: "Projects",
    meta: projects.length ? `${projects.length} registered` : "none yet",
    link: { text: "+ New project" },
    onLink: () => projectModal(state, { onCreated: () => location.reload() }),
    body: [body], flush: true,
  });

  if (!projects.length) {
    body.append(empty({
      title: "No projects registered",
      text: "Run  drydock init  in a git repo — or register one here with New project.",
      icon: ICONS.ship,
    }));
    return wrap;
  }

  const tbl = el("table", { class: "tbl" }, [
    el("thead", {}, [el("tr", {}, [
      el("th", { text: "Slug" }),
      el("th", { text: "Name" }),
      el("th", { text: "Repo path" }),
      el("th", { text: "Prefix" }),
    ])]),
    el("tbody", {}, projects.map((p) => el("tr", {}, [
      el("td", { class: "mono", text: p.slug, style: "width:160px" }),
      el("td", { text: p.name || p.slug }),
      el("td", { class: "mono muted", style: "font-size:12px", text: p.root_path || "—" }),
      el("td", { class: "mono", style: "width:70px", text: p.ticket_prefix || "—" }),
    ]))),
  ]);
  body.append(tbl);
  return wrap;
}
