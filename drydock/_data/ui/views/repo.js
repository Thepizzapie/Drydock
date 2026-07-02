// Repo — the project's code. Browse the tree, watch the working tree, read history.
import { api } from "../api.js";
import { el, card, pill, btn, empty, skeleton, relTime, modal, clickable, clear, toast, ICONS } from "../ui.js";

const IC_FOLDER = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3.5 6.5a2 2 0 0 1 2-2h4.2l2 2.5h6.8a2 2 0 0 1 2 2v8.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/></svg>';
const IC_FILE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M6.5 3.5H14l4 4v13H6.5z"/><path d="M13.5 3.5v4.5H18"/></svg>';

export async function repoView(root, { state }) {
  root.append(el("div", { class: "page-h" }, [
    el("div", {}, [
      el("h2", { class: "t", text: "Repo" }),
      el("div", { class: "sub", text: "The project's code — current changes and history." }),
    ]),
  ]));

  if (!state.project) {
    root.append(el("div", { class: "card" }, [el("div", { class: "bd" }, [
      empty({
        title: "No project yet",
        text: "Run  drydock init  in a git repo, then refresh — the repo view fills in.",
        icon: ICONS.ship,
      }),
    ])]));
    return;
  }

  const loading = el("div", { class: "stack" }, [skeleton(2), skeleton(4)]);
  root.append(loading);

  let repo;
  try { repo = await api.repo(state.project); }
  catch (e) { loading.replaceWith(empty({ title: "Couldn't read the repo", text: e.message })); return; }
  loading.remove();

  if (!repo.is_git) {
    root.append(el("div", { class: "card" }, [el("div", { class: "bd" }, [
      empty({
        title: "Not a git repository",
        text: "Register the project with a repo path to see history.",
        icon: ICONS.ship,
      }),
    ])]));
    return;
  }

  const main = el("div", { class: "grid g-main" });
  main.append(browserCard(state, repo));
  main.append(el("div", { class: "stack" }, [workingTreeCard(repo), historyCard(state, repo)]));
  root.append(main);
}

// ---- file browser ------------------------------------------------------------

function browserCard(state, repo) {
  const rootLabel = `${state.project} · ${repo.branch || "HEAD"}`;
  const crumbs = el("div", {
    style: "display:flex;flex-wrap:wrap;align-items:center;padding:11px 18px;border-bottom:1px solid var(--line-2);font-family:var(--mono);font-size:12px",
  });
  const body = el("div", {});
  const wrap = card({ title: "Files", meta: "click a file to read it", body: [crumbs, body], flush: true });

  const join = (base, name) => (base ? `${base}/${name}` : name);

  function crumbSeg(label, onGo) {
    if (!onGo) return el("span", { style: "color:var(--ink);font-weight:600", text: label });
    const b = el("button", {
      style: "font-family:var(--mono);font-size:12px;font-weight:600;color:var(--steel-blue);padding:0",
      text: label, onclick: onGo,
    });
    return b;
  }

  function renderCrumbs(dirPath, fileName) {
    clear(crumbs);
    const parts = dirPath ? dirPath.split("/").filter(Boolean) : [];
    const sep = () => el("span", { class: "muted", style: "padding:0 5px", text: "/" });
    const rootIsLast = !parts.length && !fileName;
    crumbs.append(crumbSeg(rootLabel, rootIsLast ? null : () => openDir("")));
    parts.forEach((p, i) => {
      crumbs.append(sep());
      const isLast = i === parts.length - 1 && !fileName;
      const target = parts.slice(0, i + 1).join("/");
      crumbs.append(crumbSeg(p, isLast ? null : () => openDir(target)));
    });
    if (fileName) { crumbs.append(sep()); crumbs.append(crumbSeg(fileName, null)); }
  }

  async function openDir(path) {
    renderCrumbs(path);
    clear(body); body.append(skeleton(4));
    let listing;
    try { listing = await api.files(state.project, path); }
    catch (e) { clear(body); body.append(empty({ title: "Couldn't list files", text: e.message })); return; }
    clear(body);

    const rows = [];
    for (const name of listing.dirs || []) {
      const tr = el("tr", { style: "cursor:pointer" }, [
        el("td", {}, [icSpan(IC_FOLDER), el("span", { class: "mono", style: "font-weight:600;color:var(--ink)", text: name })]),
        el("td", { class: "r muted", style: "font-size:12px;width:90px", text: "—" }),
      ]);
      clickable(tr, () => openDir(join(path, name)));
      rows.push(tr);
    }
    for (const f of listing.files || []) {
      const tr = el("tr", { style: "cursor:pointer" }, [
        el("td", {}, [icSpan(IC_FILE), el("span", { class: "mono", text: f.name })]),
        el("td", { class: "r muted", style: "font-size:12px;width:90px", text: fmtSize(f.size) }),
      ]);
      clickable(tr, () => openFile(join(path, f.name)));
      rows.push(tr);
    }

    if (!rows.length) {
      body.append(empty({ title: "Empty directory", text: "Nothing at this path." }));
      return;
    }
    body.append(el("table", { class: "tbl" }, [el("tbody", {}, rows)]));
  }

  async function openFile(path) {
    const parts = path.split("/");
    const name = parts.pop();
    const dirPath = parts.join("/");
    renderCrumbs(dirPath, name);
    clear(body); body.append(skeleton(4));

    const back = el("div", {}, [btn("← Back to files", { kind: "ghost", sm: true, onClick: () => openDir(dirPath) })]);
    const frame = (kids) => el("div", {
      style: "padding:12px 18px 16px;display:flex;flex-direction:column;gap:12px",
    }, [back, ...kids]);

    let f;
    try { f = await api.file(state.project, path); }
    catch (e) { clear(body); body.append(frame([empty({ title: "Couldn't open the file", text: e.message })])); return; }
    clear(body);

    if (!f.found) { body.append(frame([empty({ title: "File not found", text: path })])); return; }
    if (f.binary) {
      body.append(frame([empty({ title: "Binary file", text: "No preview — open it in your editor." })]));
      return;
    }

    const code = el("div", { class: "code", style: "max-height:560px" }, [
      el("div", { class: "bar" }, [
        el("span", { class: "dot" }), el("span", { class: "dot" }), el("span", { class: "dot" }),
        el("span", { style: "font-size:11px;color:var(--steel)", text: path }),
      ]),
      el("pre", { text: f.content || "" }),
    ]);
    const kids = [code];
    if (f.truncated) {
      kids.push(el("div", { class: "muted", style: "font-size:11.5px", text: "Truncated — the file is longer than shown here." }));
    }
    body.append(frame(kids));
  }

  openDir("");
  return wrap;
}

// ---- working tree ------------------------------------------------------------

function workingTreeCard(repo) {
  const changes = repo.changes || [];
  const kids = [el("div", { style: "margin-bottom:12px" }, [pill(repo.branch || "HEAD", "navy")])];

  if (!changes.length) {
    kids.push(empty({ title: "Clean", text: "No uncommitted changes." }));
  } else {
    kids.push(el("div", { style: "display:flex;flex-direction:column;gap:7px" }, changes.map((c) =>
      el("div", { style: "display:flex;align-items:center;gap:9px;min-width:0" }, [
        el("span", { class: `pill ${statusKind(c.status)}`, style: "font-family:var(--mono);flex:none", text: String(c.status || "").trim() || "?" }),
        el("span", { class: "mono", style: "font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap", text: c.path }),
      ]))));
  }

  return card({
    title: "Working tree",
    meta: changes.length ? `${changes.length} changed` : "clean",
    body: kids,
  });
}

function statusKind(s) {
  s = String(s || "").trim();
  if (s.includes("D")) return "deny";
  if (s.includes("A") || s.includes("?")) return "ok";
  return "info";
}

// ---- history -----------------------------------------------------------------

function historyCard(state, repo) {
  const commits = repo.commits || [];
  const feed = el("div", { class: "feed" });

  if (!commits.length) {
    feed.append(empty({ title: "No commits yet", text: "History shows up after the first commit." }));
  } else {
    for (const c of commits) {
      const row = el("div", { class: "row", style: "grid-template-columns:64px 1fr auto;cursor:pointer" }, [
        el("span", { class: "time", text: String(c.sha || "").slice(0, 7) }),
        el("span", { class: "res", text: c.message || "" }),
        el("span", { class: "muted", style: "font-size:11px;white-space:nowrap", text: `${c.author || "—"} · ${relTime(c.when)}` }),
      ]);
      clickable(row, () => showCommit(state, c));
      feed.append(row);
    }
  }

  return card({
    title: "History",
    meta: commits.length ? `last ${commits.length} commits` : "none yet",
    body: [feed], flush: true,
  });
}

async function showCommit(state, c) {
  let out;
  try { out = await api.repoCommit(state.project, c.sha); }
  catch (e) { toast(e.message, "err"); return; }
  modal({
    title: `Commit ${String(c.sha || "").slice(0, 7)}`,
    body: [el("div", { class: "code", style: "max-height:60vh" }, [el("pre", { text: out.text || "" })])],
  });
}

// ---- utils -------------------------------------------------------------------

function icSpan(svg) {
  return el("span", { html: svg, style: "display:inline-block;width:15px;height:15px;vertical-align:-3px;margin-right:8px;color:var(--ink-3)" });
}

function fmtSize(n) {
  if (n == null || isNaN(n)) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}
