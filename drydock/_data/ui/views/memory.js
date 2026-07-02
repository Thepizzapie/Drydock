// Memory — the project's institutional recall. Search what agents learned,
// review the decisions that still stand, and read the active handoff.
import { api } from "../api.js";
import { el, card, pill, empty, skeleton, relTime, ICONS } from "../ui.js";

export async function memoryView(root, { state }) {
  if (!state.project) { root.append(noProject()); return; }

  root.append(el("div", { class: "page-h" }, [
    el("div", {}, [
      el("h2", { class: "t", text: "Memory" }),
      el("div", { class: "sub", text: "Search recall, review decisions, read the handoff." }),
    ]),
  ]));

  const main = el("div", { class: "grid g-main" });
  root.append(main);

  // ---- left: search + results --------------------------------------------
  const left = el("div", { class: "stack" });
  const input = el("input", { type: "search", placeholder: "Search memory…", autocomplete: "off" });
  const search = el("div", { class: "search" }, [el("span", { class: "ic", html: ICONS.search }), input]);
  const results = el("div", { class: "bd flush" });
  left.append(card({
    title: "Recall", meta: "pinned + searchable",
    body: [el("div", { style: "padding:14px 18px" }, [search]), results], flush: true,
  }));
  main.append(left);

  // ---- right: decisions + handoff ----------------------------------------
  const right = el("div", { class: "stack" });
  const decHost = el("div", { class: "bd flush" });
  right.append(card({ title: "Decisions", meta: "active only", body: [decHost], flush: true }));
  const handoffHost = el("div", {});
  right.append(card({ title: "Active handoff", meta: "where to pick up", body: [handoffHost] }));
  main.append(right);

  // ---- wire search --------------------------------------------------------
  let seq = 0;
  async function runSearch(q) {
    const mine = ++seq;
    results.replaceChildren(skeleton(4));
    let hits;
    try { hits = await api.memorySearch(state.project, q); }
    catch (e) { if (mine === seq) results.replaceChildren(el("div", { class: "bd" }, [empty({ title: "Search failed", text: e.message })])); return; }
    if (mine !== seq) return; // a newer query already landed

    if (!hits.length) {
      results.replaceChildren(el("div", { class: "bd" }, [empty({
        title: q ? "No matches" : "No memory yet",
        text: q ? "Try a shorter or different term." : "Decisions, notes, and handoffs an agent writes land here.",
        icon: ICONS.memory,
      })]));
      return;
    }
    results.replaceChildren(...hits.map(memoryHit));
  }

  let debounce;
  input.addEventListener("input", () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => runSearch(input.value.trim()), 250);
  });

  // ---- load decisions + handoff, and seed empty-query recall -------------
  runSearch("");
  loadDecisions(state, decHost);
  loadHandoff(state, handoffHost);
}

function memoryHit(m) {
  const top = el("div", { class: "top" }, [
    el("span", { class: "who", text: m.title || "Untitled" }),
    m.kind && pill(m.kind, "info"),
    m.pinned && pill("Pinned", "navy"),
    el("span", { class: "age", text: m.tags && m.tags.length ? m.tags.slice(0, 2).join(" · ") : "" }),
  ]);
  const snippet = (m.body || "").slice(0, 180);
  return el("div", { class: "ask-item" }, [
    top,
    snippet && el("div", { class: "what", style: "margin-bottom:0", text: snippet + ((m.body || "").length > 180 ? "…" : "") }),
  ]);
}

async function loadDecisions(state, host) {
  host.replaceChildren(skeleton(3));
  let decisions;
  try { decisions = await api.decisions(state.project); }
  catch (e) { host.replaceChildren(el("div", { class: "bd" }, [empty({ title: "Couldn't load decisions", text: e.message })])); return; }

  if (!decisions.length) {
    host.replaceChildren(el("div", { class: "bd" }, [empty({
      title: "No decisions logged",
      text: "When an agent makes a call worth remembering, it records the rationale here.",
    })]));
    return;
  }
  host.replaceChildren(...decisions.map((d) => el("div", { class: "ask-item" }, [
    el("div", { class: "top" }, [
      el("span", { style: "font-size:13px;font-weight:600", text: d.title }),
      el("span", { class: "age", text: relTime(d.created_at) }),
    ]),
    d.rationale && el("div", { class: "what", style: "margin-bottom:0", text: d.rationale }),
  ])));
}

async function loadHandoff(state, host) {
  host.replaceChildren(el("div", { class: "skel", style: "height:60px" }));
  let ov;
  try { ov = await api.overview(state.project); }
  catch { host.replaceChildren(empty({ title: "No handoff", text: "The active handoff will show here once one is written." })); return; }

  const h = ov.handoff;
  if (!h) {
    host.replaceChildren(empty({ title: "No active handoff", text: "The last agent to hand off leaves a summary and next steps here." }));
    return;
  }

  const kids = [
    el("div", { style: "font-size:13px;line-height:1.6", text: h.summary || h.current_state || "In progress" }),
  ];
  const steps = h.next_steps;
  if (steps && steps.length) {
    kids.push(el("div", { class: "muted", style: "margin-top:12px;font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase", text: "Next steps" }));
    const list = el("ul", { style: "margin:6px 0 0;padding-left:18px;font-size:13px;line-height:1.6" });
    (Array.isArray(steps) ? steps : String(steps).split("\n")).filter(Boolean).forEach((s) =>
      list.append(el("li", { text: typeof s === "string" ? s : (s.text || s.title || String(s)) })));
    kids.push(list);
  }
  if (h.created_at) kids.push(el("div", { class: "muted", style: "margin-top:12px;font-size:12px", text: `Handed off ${relTime(h.created_at)}` }));
  host.replaceChildren(...kids);
}

function noProject() {
  return el("div", { class: "card", style: "margin-top:20px" }, [el("div", { class: "bd" }, [
    empty({
      title: "No project yet",
      text: "Run  drydock init  in a git repo, then refresh. Recall, decisions, and handoffs build up as agents work.",
      icon: ICONS.ship,
    }),
  ])]);
}
