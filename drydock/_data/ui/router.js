// Minimal hash router. Routes render into #view. State (current project) is shared.

export const state = { project: null, projects: [], tiers: null };

const routes = {};
export function route(name, fn) { routes[name] = fn; }

function parseHash() {
  const h = (location.hash || "#/overview").replace(/^#\/?/, "");
  const [path, query] = h.split("?");
  const parts = path.split("/").filter(Boolean);
  const params = {};
  if (query) for (const kv of query.split("&")) { const [k, v] = kv.split("="); params[k] = decodeURIComponent(v || ""); }
  return { name: parts[0] || "overview", rest: parts.slice(1), params };
}

let _onChange = null;
export function onRouteChange(fn) { _onChange = fn; }

export async function render() {
  const { name, rest, params } = parseHash();
  const view = document.getElementById("view");
  const fn = routes[name] || routes["overview"];
  if (_onChange) _onChange(name);
  view.innerHTML = "";
  try {
    await fn(view, { rest, params, state });
  } catch (e) {
    view.innerHTML = `<div class="empty"><h4>Couldn't load this view</h4><p>${e.message}</p></div>`;
  }
}

export function navigate(hash) { location.hash = hash; }

window.addEventListener("hashchange", render);
