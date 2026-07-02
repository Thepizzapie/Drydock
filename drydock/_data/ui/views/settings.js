// Settings — local config + environment. Also the first-run reference:
// everything runs on this machine, nothing leaves. Keep it clean and reassuring.
import { api } from "../api.js";
import { el, card, pill, empty, skeleton, ICONS } from "../ui.js";

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
  stack.append(envSection(doc));
  stack.append(projectsSection(state));
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

// ---- Projects ---------------------------------------------------------------

function projectsSection(state) {
  const projects = (state && state.projects) || [];
  const body = el("div", { class: "bd flush" });
  const wrap = card({ title: "Projects", meta: projects.length ? `${projects.length} registered` : "none yet", body: [body], flush: true });

  if (!projects.length) {
    body.append(empty({
      title: "No projects registered",
      text: "Run  drydock init  in a git repo and it registers here.",
      icon: ICONS.ship,
    }));
    return wrap;
  }

  const tbl = el("table", { class: "tbl" }, [el("tbody", {},
    projects.map((p) => el("tr", {}, [
      el("td", { class: "mono", text: p.slug, style: "width:220px" }),
      el("td", { text: p.name || p.slug }),
    ])))]);
  body.append(tbl);
  return wrap;
}
