// Boot: build the shell, load projects + tier, register views, start the router.
import { api } from "./api.js";
import { el, ICONS } from "./ui.js";
import { render, route, state, onRouteChange, navigate } from "./router.js";

import { overviewView } from "./views/overview.js";
import { approvalsView, auditView } from "./views/approvals.js";
import { runsView, runView } from "./views/runs.js";
import { workView, ticketView } from "./views/work.js";
import { memoryView } from "./views/memory.js";
import { agentsView, studioView } from "./views/agents.js";
import { settingsView } from "./views/settings.js";

const NAV = [
  { name: "overview", label: "Overview", icon: ICONS.overview },
  { name: "approvals", label: "Approvals", icon: ICONS.ask, badge: "asks" },
  { name: "runs", label: "Runs", icon: ICONS.runs },
  { name: "work", label: "Work", icon: ICONS.ticket },
  { name: "memory", label: "Memory", icon: ICONS.memory },
  { name: "audit", label: "Audit", icon: ICONS.audit },
  { name: "agents", label: "Agents", icon: ICONS.agents },
  { name: "studio", label: "Studio", icon: ICONS.studio },
  { name: "settings", label: "Settings", icon: ICONS.settings },
];

function buildShell() {
  const navLinks = NAV.map((n) =>
    el("a", { href: `#/${n.name}`, dataset: { nav: n.name } }, [
      el("span", { class: "ic", html: n.icon }),
      el("span", { text: n.label }),
      n.badge && el("span", { class: "count", dataset: { badge: n.badge }, style: "display:none" }),
    ]));

  const rail = el("aside", { class: "rail" }, [
    el("div", { class: "brand" }, [
      el("img", { src: "./assets/logo-horizontal.png", alt: "Drydock", class: "logo-full" }),
      el("img", { src: "./assets/mark.png", alt: "Drydock", class: "logo-mark" }),
    ]),
    el("nav", { class: "nav" }, navLinks),
    el("div", { class: "spacer" }),
    el("div", { class: "local" }, [
      el("span", { class: "status", html: '<span class="dot"></span>' }),
      el("span", { text: "All systems local" }),
    ]),
  ]);

  const projSelect = el("select", { class: "input", style: "width:auto;padding:6px 10px;font-size:12.5px",
    onchange: (e) => { state.project = e.target.value; render(); } });

  const tierBadge = el("div", { class: "tier-badge", id: "tierBadge" }, [
    el("span", { class: "ring" }), el("span", { text: "Detecting tier…" })]);

  const topbar = el("header", { class: "topbar" }, [
    el("h1", { id: "pageTitle", text: "Mission Control" }),
    el("span", { class: "crumb", id: "crumb" }),
    el("div", { class: "right" }, [
      projSelect,
      tierBadge,
      el("div", { class: "status" }, [el("span", { class: "dot" }), el("span", { text: "Local · this machine" })]),
      el("span", { class: "ic", html: ICONS.windows, style: "width:18px;color:var(--steel-blue)" }),
    ]),
  ]);

  const main = el("main", { class: "main" }, [
    topbar,
    el("div", { class: "canvas wide", id: "view" }),
    el("footer", { class: "foot" }, [
      el("span", { text: "Drydock v0.1" }), el("span", { class: "sep", text: "·" }),
      el("span", { text: "Open source · Apache-2.0" }), el("span", { class: "sep", text: "·" }),
      el("span", { text: "Runs locally on your hardware" }),
    ]),
  ]);

  document.getElementById("app").append(rail, main);
  return { projSelect, tierBadge };
}

const TITLES = {
  overview: ["Mission Control", "agents, governed and observed"],
  approvals: ["Approvals", "actions waiting on your decision"],
  runs: ["Runs", "live agent sessions in sandboxes"],
  work: ["Work", "tickets and pickup-ready briefs"],
  memory: ["Memory", "recall, decisions, and handoffs"],
  audit: ["Audit", "every decision, recorded locally"],
  agents: ["Agents", "the registry of who can do what"],
  studio: ["Agent Studio", "author and version agents"],
  settings: ["Settings", "local configuration"],
};

function registerViews() {
  route("overview", overviewView);
  route("approvals", approvalsView);
  route("audit", auditView);
  route("runs", runsView);
  route("run", runView);
  route("work", workView);
  route("ticket", ticketView);
  route("memory", memoryView);
  route("agents", agentsView);
  route("studio", studioView);
  route("settings", settingsView);
}

function highlightNav(name) {
  // sub-routes belong to a parent nav item (run → runs, ticket → work)
  const parent = name === "run" ? "runs" : name === "ticket" ? "work" : name;
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === parent));
  const t = TITLES[parent] || TITLES.overview;
  document.getElementById("pageTitle").textContent = t[0];
  document.getElementById("crumb").textContent = t[1];
}

async function refreshBadges() {
  if (!state.project) return;
  try {
    const asks = await api.asks(state.project);
    document.querySelectorAll('[data-badge="asks"]').forEach((b) => {
      if (asks.length) { b.textContent = asks.length; b.style.display = ""; }
      else b.style.display = "none";
    });
  } catch (_) {}
}

async function loadTier(badge) {
  try {
    const t = await api.tiers();
    state.tiers = t;
    const rec = t.recommended;
    const label = { 0: "Tier 0 · policy-only", 1: "Tier 1 · WSL2", 2: "Tier 2 · Docker" }[rec];
    const pct = { 0: 34, 1: 78, 2: 100 }[rec];
    badge.querySelector(".ring").style.setProperty("--p", pct + "%");
    badge.lastChild.textContent = label;
  } catch (_) { badge.lastChild.textContent = "Tier 0"; }
}

async function boot() {
  const { projSelect, tierBadge } = buildShell();
  registerViews();
  onRouteChange(highlightNav);

  try {
    const projects = await api.projects();
    state.projects = projects;
    if (projects.length) {
      state.project = projects[0].slug;
      projSelect.innerHTML = "";
      projects.forEach((p) => projSelect.append(el("option", { value: p.slug, text: p.name })));
    } else {
      projSelect.replaceWith(el("span", { class: "muted", text: "no project — run `drydock init`" }));
    }
  } catch (e) { /* server may be starting */ }

  loadTier(tierBadge);
  await render();
  refreshBadges();
  setInterval(refreshBadges, 8000);
}

boot();
export { navigate };
