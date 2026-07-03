// Boot: build the shell, load projects + tier, register views, start the router.
import { api } from "./api.js";
import { el, ICONS } from "./ui.js";
import { render, route, state, onRouteChange, navigate } from "./router.js";

import { overviewView } from "./views/overview.js";
import { approvalsView, auditView } from "./views/approvals.js";
import { runsView, runView } from "./views/runs.js";
import { workView, ticketView } from "./views/work.js";
import { repoView } from "./views/repo.js";
import { memoryView } from "./views/memory.js";
import { agentsView } from "./views/agents.js";
import { settingsView } from "./views/settings.js";

const NAV = [
  { name: "overview", label: "Overview", icon: ICONS.overview },
  { name: "approvals", label: "Approvals", icon: ICONS.ask, badge: "asks" },
  { name: "runs", label: "Runs", icon: ICONS.runs },
  { name: "work", label: "Work", icon: ICONS.ticket },
  { name: "repo", label: "Repo", icon: ICONS.diff },
  { name: "memory", label: "Memory", icon: ICONS.memory },
  { name: "audit", label: "Audit", icon: ICONS.audit },
  { name: "agents", label: "Agents", icon: ICONS.agents },
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
    el("a", { class: "brand", href: "#/overview", "aria-label": "Drydock" },
      [el("img", { src: "./assets/mark.png", alt: "Drydock", class: "logo-mark" })]),
    el("nav", { class: "nav" }, navLinks),
    el("div", { class: "spacer" }),
    el("span", { class: "pulse", title: "All systems local" }, [el("i")]),
  ]);

  const projSelect = el("select", { "aria-label": "Project",
    onchange: async (e) => {
      if (e.target.value === "__new__") {
        e.target.value = state.project || "";
        const { projectModal } = await import("./ui.js");
        projectModal(state, { onCreated: async (p) => {
          state.projects = await api.projects();
          fillProjects(projSelect);
          projSelect.value = p.slug;
          state.project = p.slug;
          render(); refreshBadges();
        } });
        return;
      }
      state.project = e.target.value;
      render(); refreshBadges();
    } });

  const projChip = el("div", { class: "projchip" }, [
    el("span", { class: "ic", html: ICONS.diff }), projSelect,
  ]);

  const statusLine = el("div", { class: "statusline", id: "statusLine" }, [
    el("span", { class: "dot" }),
    el("span", { html: "local · <b>detecting tier…</b>" }),
  ]);

  const topbar = el("header", { class: "topbar" }, [
    projChip,
    el("div", { class: "right" }, [statusLine]),
  ]);

  const main = el("main", { class: "main" }, [
    topbar,
    el("div", { class: "canvas wide", id: "view" }),
  ]);

  document.getElementById("app").append(rail, main);
  return { projSelect, statusLine };
}

const TITLES = {
  overview: ["Mission Control", "agents, governed and observed"],
  approvals: ["Approvals", "actions waiting on your decision"],
  runs: ["Runs", "live agent sessions in sandboxes"],
  work: ["Work", "tickets and pickup-ready briefs"],
  repo: ["Repo", "code, changes, and history"],
  memory: ["Memory", "recall, decisions, and handoffs"],
  audit: ["Audit", "every decision, recorded locally"],
  agents: ["Agents", "who can act, and exactly what they may do"],
  settings: ["Settings", "local configuration and integrations"],
};

function registerViews() {
  route("overview", overviewView);
  route("approvals", approvalsView);
  route("audit", auditView);
  route("runs", runsView);
  route("run", runView);
  route("work", workView);
  route("ticket", ticketView);
  route("repo", repoView);
  route("memory", memoryView);
  route("agents", agentsView);
  route("studio", agentsView); // Studio merged into Agents; old links still land
  route("settings", settingsView);
}

function highlightNav(name) {
  // sub-routes belong to a parent nav item (run → runs, ticket → work, studio → agents)
  const parent = name === "run" ? "runs" : name === "ticket" ? "work"
    : name === "studio" ? "agents" : name;
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === parent));
}

function fillProjects(select) {
  select.innerHTML = "";
  state.projects.forEach((p) => select.append(el("option", { value: p.slug, text: p.name })));
  select.append(el("option", { value: "__new__", text: "＋ New project…" }));
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

async function loadTier(statusLine) {
  const label = { 0: "tier 0 · policy-only", 1: "tier 1 · WSL2", 2: "tier 2 · Docker" };
  try {
    const t = await api.tiers();
    state.tiers = t;
    statusLine.querySelector("span:last-child").innerHTML = `local · <b>${label[t.recommended] || "tier 0"}</b>`;
  } catch (_) { statusLine.querySelector("span:last-child").innerHTML = "local · <b>tier 0</b>"; }
}

async function boot() {
  const { projSelect, statusLine } = buildShell();
  registerViews();
  onRouteChange(highlightNav);

  try {
    const projects = await api.projects();
    state.projects = projects;
    if (projects.length) {
      state.project = projects[0].slug;
    }
    fillProjects(projSelect);
    if (state.project) projSelect.value = state.project;
  } catch (e) { /* server may be starting */ }

  loadTier(statusLine);
  await render();
  refreshBadges();
  setInterval(refreshBadges, 8000);
}

boot();
export { navigate };
