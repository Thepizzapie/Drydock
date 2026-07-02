// REST client for the Drydock server. All calls are same-origin, localhost.

async function req(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).error || detail; } catch (_) {}
    throw new Error(`${res.status}: ${detail}`);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

export const api = {
  get: (p) => req("GET", p),
  post: (p, b) => req("POST", p, b),

  projects: () => api.get("/api/projects"),
  createProject: (body) => api.post("/api/projects", body),
  overview: (proj) => api.get(`/api/projects/${proj}/overview`),
  tickets: (proj, status) => api.get(`/api/projects/${proj}/tickets` + (status ? `?status=${status}` : "")),
  ticket: (proj, ref) => api.get(`/api/projects/${proj}/tickets/${ref}`),
  createTicket: (proj, body) => api.post(`/api/projects/${proj}/tickets`, body),
  brief: (proj, taskId) => api.get(`/api/tasks/${taskId}/brief?project=${proj}`),
  repo: (proj) => api.get(`/api/projects/${proj}/repo`),
  repoCommit: (proj, sha) => api.get(`/api/projects/${proj}/repo/commit/${sha}`),
  files: (proj, path = "") => api.get(`/api/projects/${proj}/files?path=${encodeURIComponent(path)}`),
  file: (proj, path) => api.get(`/api/projects/${proj}/file?path=${encodeURIComponent(path)}`),
  mcpInfo: () => api.get("/api/system/mcp"),
  installHooks: (proj) => api.post(`/api/projects/${proj}/hooks/install`, {}),
  memorySearch: (proj, q, k = 8) => api.get(`/api/projects/${proj}/memory/search?q=${encodeURIComponent(q)}&k=${k}`),
  decisions: (proj) => api.get(`/api/projects/${proj}/decisions`),
  runs: (proj, status) => api.get(`/api/projects/${proj}/runs` + (status ? `?status=${status}` : "")),
  run: (id) => api.get(`/api/runs/${id}`),
  runDiff: (id) => api.get(`/api/runs/${id}/diff`),
  audit: (proj, filters = {}) => {
    const q = Object.entries(filters).filter(([, v]) => v)
      .map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
    return api.get(`/api/projects/${proj}/audit` + (q ? `?${q}` : ""));
  },
  tokens: (proj) => api.get(`/api/projects/${proj}/stats/tokens`),
  asks: (proj) => api.get(`/api/asks` + (proj ? `?project=${proj}` : "")),
  resolveAsk: (id, resolution) => api.post(`/api/asks/${id}/resolve`, { resolution }),
  dispatch: (proj, body) => api.post(`/api/projects/${proj}/dispatch`, body),
  agents: (proj) => api.get(`/api/projects/${proj}/agents`),
  agent: (proj, name) => api.get(`/api/projects/${proj}/agents/${name}`),
  authorAgent: (proj, spec) => api.post(`/api/projects/${proj}/agents`, spec),
  models: () => api.get("/api/system/models"),
  tools: () => api.get("/api/system/tools"),
  tiers: () => api.get("/api/system/tiers"),
  doctor: () => api.get("/api/system/doctor"),
  health: () => api.get("/api/health"),
};

// live event stream for a run (Server-Sent Events)
export function streamRun(runId, onEvent, onEnd) {
  const src = new EventSource(`/api/runs/${runId}/events`);
  src.onmessage = (e) => { try { onEvent(JSON.parse(e.data)); } catch (_) {} };
  src.addEventListener("end", (e) => { src.close(); if (onEnd) onEnd(JSON.parse(e.data || "{}")); });
  src.onerror = () => src.close();
  return () => src.close();
}
