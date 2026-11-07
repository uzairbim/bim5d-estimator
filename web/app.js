import * as THREE from "three";
import { Viewer } from "./viewer.js";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const fmt = (n, d = 0) => (n === null || n === undefined || isNaN(n)) ? "–" : Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const TRADE_COLORS = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2", "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac", "#86bcb6", "#d4a6c8", "#8cd17d", "#f1ce63"];
const STAGE_COLORS = { "1 Substructure": "#9c755f", "2 Frame & floors": "#4e79a7", "3 Roof": "#b07aa1", "4 Envelope & walls": "#f28e2b", "5 Services": "#59a14f", "6 Finishes": "#76b7b2", "7 Fit-out": "#edc948", "9 Other": "#bab0ac" };

const S = {
  lib: null, projects: [], project: null, version: null, els: {}, est: null, geo: null,
  mode: "cost", selected: null, highlight: null, level: "", time: null, playing: null,
  compare: null, mapFilter: "unpriced", mapSearch: "", suggestions: {},
};

// ---------- helpers ----------
async function api(url, opts = {}) {
  if (opts.json !== undefined) {
    opts = { ...opts, body: JSON.stringify(opts.json), headers: { "Content-Type": "application/json" } };
    delete opts.json;
  }
  const r = await fetch(url, opts);
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(typeof d.detail === "string" ? d.detail : (d.error || r.statusText));
  }
  return r.json();
}
let toastTimer;
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), 3500);
}
function busy(on, text, frac) {
  $("#busy").hidden = !on;
  if (text) $("#busyText").textContent = text;
  $("#busyBar").style.width = `${Math.round((frac || 0) * 100)}%`;
  $("#busyBar").parentElement.hidden = frac === undefined;
}
const cur = () => S.est?.currency || "";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- viewer ----------
const viewer = new Viewer($("#canvas"), { onPick: (g) => select(g, true) });

function ramp(t) {
  const stops = ["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c"].map((h) => new THREE.Color(h));
  const x = Math.min(Math.max(t, 0), 1) * (stops.length - 1), i = Math.min(Math.floor(x), stops.length - 2);
  return stops[i].clone().lerp(stops[i + 1], x - i);
}

function paint() {
  const est = S.est;
  if (!est) return;
  const pe = est.per_element;
  const totals = Object.values(pe).map((p) => p.total).filter((v) => v > 0).sort((a, b) => a - b);
  const p95 = totals[Math.floor(totals.length * 0.95)] || 1;
  const trades = Object.keys(est.by_trade);
  const mainTrade = S._mainTrade || {};
  const flagged = new Set(est.checks.geometry_flagged), unc = new Set(est.checks.unclassified), exc = new Set(est.checks.excluded);
  const sched = est.schedule?.elements || {};
  const cmp = S.mode === "changes" && S.compare ? S.compare.status : null;
  let legend = "";
  if (S.time !== null) {
    legend = `<b>Week ${fmt(S.time, 1)}</b><div class="key"><span class="sw" style="background:#f59e0b"></span>Being built</div><div class="key"><span class="sw" style="background:#9aa4b2"></span>Done</div>`;
  } else if (S.mode === "cost") legend = `<div class="ramp"></div><div class="ramp-l"><span>low</span><span>${fmt(p95)}+ ${cur()}</span></div>`;
  else if (S.mode === "trade") legend = trades.map((t, i) => `<div class="key"><span class="sw" style="background:${TRADE_COLORS[i % TRADE_COLORS.length]}"></span>${esc(t)}</div>`).join("");
  else if (S.mode === "check") legend = `<div class="key"><span class="sw" style="background:#15803d"></span>Priced</div><div class="key"><span class="sw" style="background:#f59e0b"></span>Shape needs review</div><div class="key"><span class="sw" style="background:#dc2626"></span>Not priced</div><div class="key"><span class="sw" style="background:#9aa4b2"></span>Excluded</div>`;
  else if (cmp) legend = `<div class="key"><span class="sw" style="background:#16a34a"></span>Added</div><div class="key"><span class="sw" style="background:#f59e0b"></span>Changed</div><div class="key"><span class="sw" style="background:#dc2626"></span>Removed</div>`;
  $("#legend").innerHTML = legend;

  viewer.paint((g) => {
    const el = S.els[g];
    if (S.level && el && el.level !== S.level) return { visible: false };
    let color, opacity = 1, visible = true;
    if (S.time !== null) {
      const t = sched[g];
      if (!t) return { visible: false };
      if (S.time < t[0]) return { visible: false };
      color = S.time < t[1] ? "#f59e0b" : "#9aa4b2";
    } else if (cmp) {
      const st = cmp[g];
      color = st === "added" ? "#16a34a" : st === "changed" ? "#f59e0b" : "#c3c9d4";
      if (st === "same") opacity = 0.18;
    } else if (S.mode === "cost") {
      const p = pe[g];
      color = p && p.total > 0 ? ramp(Math.sqrt(p.total / p95)) : "#999999";
    } else if (S.mode === "trade") {
      const t = mainTrade[g];
      color = t ? TRADE_COLORS[trades.indexOf(t) % TRADE_COLORS.length] : "#999999";
    } else {
      color = unc.has(g) ? "#dc2626" : exc.has(g) ? "#9aa4b2" : flagged.has(g) ? "#f59e0b" : "#15803d";
    }
    if (S.highlight && !S.highlight.has(g)) opacity = Math.min(opacity, 0.1);
    return { color, opacity, visible, emissive: g === S.selected ? 0x2244ff : 0x000000 };
  });
  for (const m of viewer.ghosts.values()) m.visible = !!cmp && (!S.level || S.els[m.userData.guid]?.level === S.level);
}

// ---------- start page ----------
async function init() {
  const [lib, samples] = await Promise.all([api("/api/library"), api("/api/samples")]);
  S.lib = lib;
  const regionOpts = Object.entries(lib.regions).map(([k, r]) => `<option value="${k}">${esc(r.name)} (${r.currency})</option>`).join("");
  $("#region").innerHTML = regionOpts;
  $("#startRegion").innerHTML = regionOpts;
  $("#startRegion").value = localStorageGet("region") || "SA";
  $("#sample").innerHTML += samples.map((s) => `<option>${esc(s)}</option>`).join("");
  await loadProjects();
  route();
}
function localStorageGet(k) { try { return localStorage.getItem("bim5d." + k); } catch { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem("bim5d." + k, v); } catch { /* ignore */ } }

async function loadProjects() {
  S.projects = await api("/api/projects");
  $("#projectsTitle").hidden = !S.projects.length;
  $("#projectList").innerHTML = S.projects.map((p) => {
    const v = p.versions[p.versions.length - 1];
    const status = !v ? "empty" : v.status === "ready" ? `${fmt(v.elements)} elements` : v.status === "error" ? "error" : "processing…";
    return `<div class="card" data-pid="${p.id}"><button class="del" data-del="${p.id}" title="Delete project">×</button>
      <h4>${esc(p.name)}</h4><div class="meta">${p.versions.length} revision${p.versions.length === 1 ? "" : "s"} · ${status}</div>
      <div class="meta">${esc(S.lib.regions[p.settings.region]?.name || p.settings.region)} · ${new Date(p.created * 1000).toLocaleDateString()}</div></div>`;
  }).join("");
  $("#projectSel").innerHTML = S.projects.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
}
$("#projectList").addEventListener("click", async (e) => {
  const del = e.target.closest("[data-del]");
  if (del) {
    e.stopPropagation();
    if (!confirm("Delete this project and all its revisions?")) return;
    await api(`/api/projects/${del.dataset.del}`, { method: "DELETE" });
    return loadProjects();
  }
  const card = e.target.closest("[data-pid]");
  if (card) go(card.dataset.pid);
});

function route() {
  const h = new URLSearchParams(location.hash.slice(1));
  const pid = h.get("p");
  if (pid && S.projects.find((p) => p.id === pid)) openProject(pid, h.get("v"));
  else showStart();
}
window.addEventListener("hashchange", route);
function go(pid, vid) { location.hash = `p=${pid}` + (vid ? `&v=${vid}` : ""); }
function showStart() {
  S.project = null;
  $("#start").hidden = false; $("#work").hidden = true; $("#projectControls").hidden = true;
  stopPlay();
  loadProjects();
}
$("#home").addEventListener("click", () => { location.hash = ""; });

async function uploadFile(file, projectId) {
  if (!file.name.toLowerCase().endsWith(".ifc")) return toast("Please choose an .ifc file.");
  const fd = new FormData();
  fd.append("file", file);
  if (projectId) fd.append("project_id", projectId);
  else fd.append("region", $("#startRegion").value);
  busy(true, `Uploading ${file.name}…`);
  try {
    const r = await api("/api/projects", { method: "POST", body: fd });
    await loadProjects();
    go(r.project_id, r.version_id);
  } catch (err) { busy(false); toast(err.message); }
}
$("#file").addEventListener("change", (e) => { const f = e.target.files[0]; if (f) uploadFile(f); e.target.value = ""; });
const drop = $("#drop");
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) uploadFile(f); });
$("#startRegion").addEventListener("change", (e) => localStorageSet("region", e.target.value));
$("#sample").addEventListener("change", async (e) => {
  if (!e.target.value) return;
  const r = await api(`/api/projects/sample/${encodeURIComponent(e.target.value)}?region=${$("#startRegion").value}`, { method: "POST" });
  e.target.value = "";
  await loadProjects();
  go(r.project_id, r.version_id);
});

// ---------- open a project ----------
async function openProject(pid, vid) {
  $("#start").hidden = true; $("#work").hidden = false; $("#projectControls").hidden = false;
  let p = await api(`/api/projects/${pid}`);
  S.project = p;
  const v = (vid && p.versions.find((x) => x.id === vid)) || [...p.versions].reverse().find((x) => x.status === "ready") || p.versions[p.versions.length - 1];
  if (!v) return toast("This project has no model yet.");
  $("#projectSel").value = pid;
  $("#region").value = p.settings.region;
  if (S.version?.id === v.id && S.est) return refresh();
  S.version = v;
  S.selected = null; S.highlight = null; S.compare = null; S.time = null; S.level = ""; S.suggestions = {};
  $("#colorMode [data-mode=changes]").hidden = true;
  if (S.mode === "changes") setMode("cost");
  renderVersions();
  // wait for processing
  while (true) {
    const st = await api(`/api/versions/${v.id}`);
    if (st.status === "ready") break;
    if (st.status === "error") { busy(false); return toast(`Could not read this model: ${st.error}`); }
    busy(true, `Measuring ${st.file_name}… (large models take a minute the first time)`, st.progress || 0.02);
    await sleep(1000);
    if (S.version?.id !== v.id) return;
  }
  busy(true, "Loading 3D model…");
  try {
    const [geo, els] = await Promise.all([Viewer.fetchGeometry(v.id), api(`/api/versions/${v.id}/elements`)]);
    S.geo = geo; S.els = els;
    viewer.load(geo);
    p = await api(`/api/projects/${pid}`);
    S.project = p; S.version = p.versions.find((x) => x.id === v.id);
    renderVersions();
    const levels = [...new Set(Object.values(els).map((e) => e.level))].sort();
    $("#levelSel").innerHTML = `<option value="">All levels</option>` + levels.map((l) => `<option>${esc(l)}</option>`).join("");
    await refresh();
  } catch (err) { toast(err.message); }
  busy(false);
}

function renderVersions() {
  const p = S.project;
  $("#versionSel").innerHTML = p.versions.map((v) => `<option value="${v.id}" ${v.status !== "ready" ? "disabled" : ""}>${esc(v.label)} · ${esc(v.file_name || "")}${v.status !== "ready" ? " (" + v.status + ")" : ""}</option>`).join("");
  $("#versionSel").value = S.version.id;
}
$("#projectSel").addEventListener("change", (e) => go(e.target.value));
$("#versionSel").addEventListener("change", (e) => go(S.project.id, e.target.value));
$("#region").addEventListener("change", (e) => saveSettings({ region: e.target.value }));

async function refresh() {
  const est = await api(`/api/projects/${S.project.id}/estimate?version=${S.version.id}`);
  S.est = est;
  S._mainTrade = {};
  const best = {};
  for (const l of est.lines) if (!best[l.guid] || l.amount > best[l.guid]) { best[l.guid] = l.amount; S._mainTrade[l.guid] = l.trade; }
  const unpriced = est.groups.filter((g) => g.recipe === null && g.source === "none").length;
  $("#mapBadge").hidden = !unpriced; $("#mapBadge").textContent = unpriced;
  renderSummary(); renderBoq(); renderMapping(); renderTime(); renderCompare();
  if (S.selected) renderElement(S.selected);
  paint();
}

async function saveSettings(changes) {
  try {
    await api(`/api/projects/${S.project.id}`, { method: "PATCH", json: changes });
    S.project = await api(`/api/projects/${S.project.id}`);
    if (S.compare) S.compare = null;
    await refresh();
  } catch (err) { toast(err.message); }
}

// ---------- summary ----------
function bars(obj) {
  const vals = Object.values(obj);
  const max = Math.max(...vals, 1);
  return `<div class="bars">${Object.entries(obj).map(([k, v]) => `<div class="bar"><span title="${esc(k)}">${esc(k)}</span><div class="track"><div class="fill" style="width:${(v / max) * 100}%"></div></div><span class="v">${fmt(v)}</span></div>`).join("")}</div>`;
}

function renderSummary() {
  const e = S.est, s = e.summary, c = e.checks, st = S.project.settings, reg = S.lib.regions[e.region];
  const sample = e.boq.some((b) => String(b.rate_source).startsWith("SAMPLE"));
  const unpriced = c.unclassified.length;
  let bench = "";
  if (s.per_m2 && s.benchmark) {
    const b = s.benchmark, inside = s.per_m2 >= b.low && s.per_m2 <= b.high;
    bench = `<div class="callout ${inside ? "ok" : ""}">Cost per m² floor area: <b>${fmt(s.per_m2)} ${e.currency}</b> on ${fmt(s.gfa)} m².
      Typical for <i>${esc(b.label)}</i>: ${fmt(b.low)}–${fmt(b.high)}. ${inside ? "Inside the usual range." : s.per_m2 < b.low ? "Lower than usual, often because services, external works or finishes are not modelled yet." : "Higher than usual. Check rates and quantities."}</div>`;
  } else if (s.per_m2) bench = `<p class="muted">Cost per m² floor area: <b>${fmt(s.per_m2)} ${e.currency}</b> on ${fmt(s.gfa)} m².</p>`;
  const rb = c.rebar;
  let rebarNote = "";
  if (rb.modeled_kg > 0 || rb.mode === "modeled") {
    rebarNote = `<div class="callout">Rebar: the model contains <b>${fmt(rb.modeled_kg)} kg</b> of modelled bars; ratios give <b>${fmt(rb.ratio_kg)} kg</b>. Now using <b>${rb.mode === "modeled" ? "modelled bars" : "ratios"}</b>.${rb.mode === "modeled" && rb.modeled_kg < rb.ratio_kg * 0.5 ? " The modelled rebar looks incomplete." : ""} Change it in the settings below.</div>`;
  }
  $("#tab-summary").innerHTML = `
    <div class="muted">${esc(S.project.name)} · ${esc(S.version.label)} · ${esc(e.region_name)}</div>
    <div class="total">${fmt(s.total)} <small>${e.currency}</small></div>
    <div class="muted">Total including ${esc(s.tax_name)} ${s.tax_pct}%</div>
    <div class="kpis">
      <div class="kpi"><span>Direct cost (measured work)</span><b>${fmt(s.direct)}</b></div>
      <div class="kpi"><span>Contingency ${s.contingency_pct}% · overhead ${s.overhead_pct}% · profit ${s.profit_pct}%</span><b>${fmt(s.contingency + s.overhead + s.profit)}</b></div>
      <div class="kpi ${unpriced ? "warn" : ""}"><span>Elements priced</span><b>${fmt(c.priced)} / ${fmt(c.elements)}</b></div>
      <div class="kpi ${c.geometry_flagged.length ? "warn" : ""}"><span>Shapes to review</span><b>${fmt(c.geometry_flagged.length)}</b></div>
    </div>
    ${unpriced ? `<div class="callout">${fmt(unpriced)} elements have no price yet. <a href="#" data-goto="mapping">Open Mapping</a> to choose what they are.</div>` : ""}
    ${bench}${rebarNote}
    <h3>By trade (${e.currency})</h3>${bars(e.by_trade)}
    <h3>Elemental cost plan</h3>
    <div class="seg" id="planSeg" style="display:inline-flex;margin-bottom:6px"><button data-plan="by_nrm1" class="on">NRM1</button><button data-plan="by_uniformat">Uniformat</button><button data-plan="by_level">Level</button></div>
    <div id="planBars">${bars(e.by_nrm1)}</div>
    <h3>Project settings</h3>
    <div class="settings">
      <label>Contingency %<input type="number" step="0.5" min="0" data-set="contingency_pct" value="${st.contingency_pct ?? reg.contingency_pct}"></label>
      <label>Overhead %<input type="number" step="0.5" min="0" data-set="overhead_pct" value="${st.overhead_pct ?? reg.overhead_pct}"></label>
      <label>Profit %<input type="number" step="0.5" min="0" data-set="profit_pct" value="${st.profit_pct ?? reg.profit_pct}"></label>
      <label>${esc(reg.tax_name)} %<input type="number" step="0.5" min="0" data-set="tax_pct" value="${st.tax_pct ?? reg.tax_pct}"></label>
      <label>Rebar based on<select data-set="rebar_mode"><option value="ratio">Ratios (kg per m³)</option><option value="modeled">Modelled rebar bars</option></select></label>
      <label>Project name<input type="text" data-set="name" value="${esc(S.project.name)}"></label>
    </div>
    ${sample ? `<p class="note">Rates marked SAMPLE are placeholders. Click <b>Rates</b> at the top to enter your own prices.</p>` : ""}`;
  $("[data-set=rebar_mode]").value = st.rebar_mode || "ratio";
  $$("[data-set]", $("#tab-summary")).forEach((inp) => inp.addEventListener("change", () => {
    const k = inp.dataset.set;
    const v = inp.type === "number" ? (inp.value === "" ? null : Number(inp.value)) : inp.value;
    saveSettings({ [k]: v });
  }));
  $$("#planSeg button").forEach((b) => b.addEventListener("click", () => {
    $$("#planSeg button").forEach((x) => x.classList.toggle("on", x === b));
    $("#planBars").innerHTML = bars(S.est[b.dataset.plan]);
  }));
  $$("[data-goto]", $("#tab-summary")).forEach((a) => a.addEventListener("click", (ev) => { ev.preventDefault(); tab(a.dataset.goto); }));
}

// ---------- BOQ ----------
function renderBoq() {
  const e = S.est;
  let html = `<p class="muted">Click a row to highlight its elements in 3D.</p><table><thead><tr><th>Item</th><th class="n">Qty</th><th class="n">Rate</th><th class="n">Amount</th></tr></thead><tbody>`;
  let trade = null;
  for (const b of e.boq) {
    if (b.trade !== trade) { trade = b.trade; html += `<tr><td colspan="4"><b>${esc(trade)}</b></td></tr>`; }
    html += `<tr class="click" data-wi="${b.work_item}"><td>${esc(b.description)}<br><span class="tag">${b.work_item}</span> <span class="muted small">${b.elements} elements</span>${String(b.rate_source).startsWith("SAMPLE") ? ' <span class="tag">sample rate</span>' : ""}</td>
      <td class="n">${fmt(b.qty, 2)} ${b.unit}</td><td class="n">${fmt(b.rate, 2)}</td><td class="n">${fmt(b.amount)}</td></tr>`;
  }
  html += `</tbody><tfoot><tr><th>Direct cost</th><th></th><th></th><th class="n">${fmt(e.summary.direct)}</th></tr></tfoot></table>`;
  $("#tab-boq").innerHTML = html;
  $$("tr[data-wi]", $("#tab-boq")).forEach((tr) => tr.addEventListener("click", () => {
    const on = tr.classList.contains("sel");
    $$("tr.sel", $("#tab-boq")).forEach((x) => x.classList.remove("sel"));
    if (on) S.highlight = null;
    else { tr.classList.add("sel"); S.highlight = new Set(e.lines.filter((l) => l.work_item === tr.dataset.wi).map((l) => l.guid)); viewer.fit([...S.highlight]); }
    paint();
  }));
}

// ---------- Mapping ----------
const recipeLabel = (n) => n === "EXCLUDE" ? "Do not price (exclude)" : (S.lib.recipes[n]?.label || n);
function recipeOptions(selected) {
  const names = Object.keys(S.lib.recipes).sort((a, b) => recipeLabel(a).localeCompare(recipeLabel(b)));
  return `<option value="">— choose —</option>` + names.map((n) => `<option value="${n}" ${n === selected ? "selected" : ""}>${esc(recipeLabel(n))}</option>`).join("") +
    `<option value="EXCLUDE" ${selected === "EXCLUDE" ? "selected" : ""}>Do not price (exclude)</option>`;
}

function renderMapping() {
  const e = S.est, maps = S.project.settings.mappings || {};
  const q = S.mapSearch.toLowerCase();
  let groups = e.groups;
  if (S.mapFilter === "unpriced") groups = groups.filter((g) => g.recipe === null && g.source === "none");
  if (S.mapFilter === "manual") groups = groups.filter((g) => g.source === "mapping" || g.source === "excluded");
  if (q) groups = groups.filter((g) => (g.type + " " + g.kind + " " + (g.recipe || "")).toLowerCase().includes(q));
  const unpricedCount = e.groups.filter((g) => g.recipe === null && g.source === "none").length;
  const anySugg = Object.keys(S.suggestions).length;
  $("#tab-mapping").innerHTML = `
    <p class="muted">Each row is one element type. Pick what it is and every element of that type is priced that way. Your choice overrides the automatic rules for this project.</p>
    <div class="toolbar">
      <div class="seg" id="mapSeg"><button data-f="unpriced">Not priced (${unpricedCount})</button><button data-f="all">All types (${e.groups.length})</button><button data-f="manual">Changed by you</button></div>
      <input type="search" id="mapSearch" placeholder="Search types" value="${esc(S.mapSearch)}">
    </div>
    ${S.lib.ai && unpricedCount ? `<div class="toolbar"><button class="btn" id="aiBtn">Suggest with AI</button>${anySugg ? '<button class="btn" id="aiAccept">Accept all suggestions with 80%+ confidence</button>' : ""}<span class="muted small">Suggestions are shown for you to check, never applied automatically.</span></div>` : ""}
    ${!S.lib.ai && unpricedCount ? `<p class="muted small">Tip: set ANTHROPIC_API_KEY on the server to get AI suggestions for unknown types, including names in other languages.</p>` : ""}
    <table><thead><tr><th>Element type</th><th class="n">Count</th><th class="n">Cost</th><th style="width:170px">Priced as</th></tr></thead><tbody>
    ${groups.slice(0, 400).map((g) => {
      const sel = maps[g.key] || g.recipe || "";
      const sug = S.suggestions[g.key];
      return `<tr class="map-row click" data-key="${esc(g.key)}"><td>${esc(g.type || "(no name)")}<br><span class="tag">${esc(g.kind.replace(/^Ifc/, ""))}</span> <span class="tag ${g.source}">${{ rule: "auto rule", mapping: "set by you", none: "no match", excluded: "excluded" }[g.source]}</span>
        ${sug ? `<div class="sugg">AI: <b>${esc(recipeLabel(sug.recipe))}</b> (${Math.round(sug.confidence * 100)}%). ${esc(sug.reason)} <button class="btn sm" data-accept="${esc(g.key)}">Accept</button></div>` : ""}</td>
        <td class="n">${g.count}</td><td class="n">${fmt(g.total)}</td>
        <td><select data-map="${esc(g.key)}">${recipeOptions(sel)}</select>${g.source === "mapping" || g.source === "excluded" ? `<button class="btn sm" data-reset="${esc(g.key)}" title="Go back to the automatic rule">Reset</button>` : ""}</td></tr>`;
    }).join("") || `<tr><td colspan="4" class="muted">${S.mapFilter === "unpriced" ? "Every element type is priced. 🎉" : "Nothing found."}</td></tr>`}
    </tbody></table>`;
  $$(`#mapSeg button`).forEach((b) => { b.classList.toggle("on", b.dataset.f === S.mapFilter); b.addEventListener("click", () => { S.mapFilter = b.dataset.f; renderMapping(); }); });
  $("#mapSearch").addEventListener("input", (ev) => { S.mapSearch = ev.target.value; clearTimeout(S._ms); S._ms = setTimeout(() => { renderMapping(); $("#mapSearch").focus(); }, 250); });
  $$("[data-map]", $("#tab-mapping")).forEach((s) => {
    s.addEventListener("click", (ev) => ev.stopPropagation());
    s.addEventListener("change", () => saveSettings({ mappings: { [s.dataset.map]: s.value || null } }));
  });
  $$("[data-reset]", $("#tab-mapping")).forEach((b) => b.addEventListener("click", (ev) => { ev.stopPropagation(); saveSettings({ mappings: { [b.dataset.reset]: null } }); }));
  $$("[data-accept]", $("#tab-mapping")).forEach((b) => b.addEventListener("click", (ev) => {
    ev.stopPropagation();
    const k = b.dataset.accept, s = S.suggestions[k];
    delete S.suggestions[k];
    saveSettings({ mappings: { [k]: s.recipe } });
  }));
  $$("tr[data-key]", $("#tab-mapping")).forEach((tr) => tr.addEventListener("click", () => {
    const g = S.est.groups.find((x) => x.key === tr.dataset.key);
    if (!g) return;
    const on = tr.classList.contains("sel");
    $$("tr.sel", $("#tab-mapping")).forEach((x) => x.classList.remove("sel"));
    if (on) S.highlight = null; else { tr.classList.add("sel"); S.highlight = new Set(g.guids); viewer.fit(g.guids); }
    paint();
  }));
  $("#aiBtn")?.addEventListener("click", async () => {
    const btn = $("#aiBtn"); btn.disabled = true; btn.textContent = "Asking AI…";
    try {
      const r = await api(`/api/projects/${S.project.id}/suggest`, { method: "POST", json: {} });
      r.suggestions.forEach((s) => (S.suggestions[s.key] = s));
      toast(`${r.suggestions.length} suggestions. Check them and click Accept.`);
    } catch (err) { toast(err.message); }
    renderMapping();
  });
  $("#aiAccept")?.addEventListener("click", () => {
    const m = {};
    for (const [k, s] of Object.entries(S.suggestions)) if (s.confidence >= 0.8) { m[k] = s.recipe; delete S.suggestions[k]; }
    if (Object.keys(m).length) saveSettings({ mappings: m }); else toast("No suggestions with 80% or more confidence.");
  });
}

// ---------- element ----------
function select(guid, show) {
  S.selected = guid;
  paint();
  if (!guid) return;
  renderElement(guid);
  if (show) tab("element");
}

function renderElement(guid) {
  const el = S.els[guid], e = S.est;
  if (!el) { $("#tab-element").innerHTML = `<p class="muted">This element is only in the other revision.</p>`; return; }
  const lines = e.lines.filter((l) => l.guid === guid);
  const pe = e.per_element[guid] || {};
  const q = el.qty;
  const g = e.groups.find((x) => x.key === el.group);
  const t = e.schedule?.elements?.[guid];
  $("#tab-element").innerHTML = `
    <div class="muted">${esc(el.kind || el.ifc_class)} · ${esc(el.level)}</div>
    <h2 style="margin:4px 0 2px;font-size:16px">${esc(el.name)}</h2>
    <div class="total">${fmt(pe.total || 0)} <small>${e.currency}</small></div>
    <div class="settings" style="grid-template-columns:1fr">
      <label>Priced as (applies to all ${g ? g.count : ""} elements of this type)<select id="elMap">${recipeOptions((S.project.settings.mappings || {})[el.group] || pe.recipe || "")}</select></label>
    </div>
    <h3>Cost breakdown</h3>
    <table><thead><tr><th>Work item</th><th class="n">Qty</th><th class="n">Rate</th><th class="n">Amount</th></tr></thead><tbody>
    ${lines.map((l) => `<tr><td>${esc(l.description)}<br><span class="muted small" title="Quantity formula">= ${esc(l.formula)}${l.waste_pct ? ` + ${l.waste_pct}% waste` : ""}</span></td><td class="n">${fmt(l.qty, 2)} ${l.unit}</td><td class="n">${fmt(l.rate, 2)}</td><td class="n">${fmt(l.amount)}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">${pe.source === "excluded" ? "Excluded from the estimate." : "Not priced. Choose what it is above."}</td></tr>`}
    </tbody></table>
    <h3>Measured from the 3D shape</h3>
    <table>${[["Volume", q.volume, "m³", "volume"], ["Wall face (one side)", q.side, "m²", "side"], ["Plan area", q.footprint, "m²", "footprint"], ["Length", q.length, "m", "length"], ["Height", q.height, "m", "height"], ["Section size", q.section, "m", "section"]]
      .map(([k, v, u, n]) => `<tr><td>${k} <span class="muted small">${n}</span></td><td class="n">${fmt(v, 3)} ${u}</td></tr>`).join("")}</table>
    ${q.check ? '<p class="note">The 3D shape is not a closed solid, so its volume is estimated. Check this element in Revit.</p>' : ""}
    ${t ? `<p class="muted">Built in weeks ${fmt(t[0], 1)}–${fmt(t[1], 1)} of the 4D sequence.</p>` : ""}
    <h3>Materials</h3><p>${el.materials.map((m) => `<span class="tag">${esc(m)}</span>`).join(" ") || '<span class="muted">none in model</span>'}</p>
    ${(el.layers || []).length ? `<table>${el.layers.map((l) => `<tr><td>${esc(l.name)}</td><td class="n">${fmt(l.t * 1000)} mm</td></tr>`).join("")}</table>` : ""}
    ${el.classification?.length ? `<h3>Classification</h3><p>${el.classification.map((c) => `<span class="tag">${esc(c)}</span>`).join(" ")}</p>` : ""}
    ${Object.keys(el.props || {}).length ? `<h3>Properties</h3><table>${Object.entries(el.props).map(([k, v]) => `<tr><td>${esc(k.replaceAll("_", " "))}</td><td>${esc(v)}</td></tr>`).join("")}</table>` : ""}`;
  $("#elMap").addEventListener("change", (ev) => saveSettings({ mappings: { [el.group]: ev.target.value || null } }));
}

// ---------- 4D ----------
function sCurve(months, total, weekNow) {
  if (!months.length) return "";
  const W = 440, H = 150, P = 28;
  const max = months[months.length - 1].cumulative || 1;
  const x = (m) => P + (m / months.length) * (W - P - 8);
  const y = (v) => H - 18 - (v / max) * (H - 30);
  let path = `M${x(0)},${y(0)}`;
  months.forEach((m) => (path += ` L${x(m.month)},${y(m.cumulative)}`));
  const barW = Math.max((W - P - 8) / months.length - 2, 1);
  const barMax = Math.max(...months.map((m) => m.amount), 1);
  const bars = months.map((m) => `<rect x="${x(m.month - 1) + 1}" y="${H - 18 - (m.amount / barMax) * (H - 30) * 0.5}" width="${barW}" height="${(m.amount / barMax) * (H - 30) * 0.5}" fill="var(--line)"/>`).join("");
  const nowX = weekNow !== null ? x(weekNow / (52 / 12)) : null;
  return `<svg class="chart" viewBox="0 0 ${W} ${H}">${bars}
    <path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2"/>
    <text x="${P}" y="10">${fmt(max)} ${cur()}</text>
    <text x="${P}" y="${H - 4}">Month 1</text><text x="${W - 60}" y="${H - 4}">Month ${months.length}</text>
    ${nowX !== null ? `<line x1="${nowX}" x2="${nowX}" y1="12" y2="${H - 18}" stroke="var(--bad)" stroke-width="1.5"/>` : ""}</svg>`;
}

function renderTime() {
  const sc = S.est.schedule;
  if (!sc || !sc.activities.length) { $("#tab-time").innerHTML = `<p class="muted">Nothing priced yet.</p>`; return; }
  const W = sc.weeks;
  const now = S.time;
  const months = S.project.settings.duration_months || 12;
  let cumNow = null;
  if (now !== null) { const m = Math.min(Math.floor(now / (52 / 12)), sc.months.length - 1); cumNow = sc.months[m]?.cumulative; }
  $("#tab-time").innerHTML = `
    <p class="muted">An automatic construction sequence: foundations, then frame floor by floor, roof, envelope, services, finishes and fit-out. Each activity's length follows its cost. Use it to check cash flow early. It is not a replacement for a full programme.</p>
    <div class="settings" style="grid-template-columns:1fr 1fr"><label>Construction time (months)<input type="number" min="1" max="120" id="durIn" value="${months}"></label>
      <label>Cost spent by now<b style="color:var(--ink);font-size:15px">${now === null ? "–" : fmt(cumNow) + " " + cur()}</b></label></div>
    <div class="player"><button class="btn sm" id="playBtn">${S.playing ? "Pause" : "Play"}</button>
      <input type="range" id="timeSlider" min="0" max="${W}" step="0.25" value="${now ?? W}">
      <span class="small" style="width:76px;text-align:right">${now === null ? "finished" : "week " + fmt(now, 1)}</span>
      <button class="btn sm" id="timeOff" ${now === null ? "disabled" : ""}>Show all</button></div>
    <h3>Cash flow (S-curve)</h3>${sCurve(sc.months, S.est.summary.total, now)}
    <h3>Sequence</h3>
    <div class="gantt">${sc.activities.map((a) => `<div class="g-row"><span title="${esc(a.stage)} · ${esc(a.level)} · ${fmt(a.cost)} ${cur()}">${esc(a.stage.slice(2))} · ${esc(a.level)}</span>
      <div class="g-track"><div class="g-bar" style="left:${(a.start / W) * 100}%;width:${Math.max(((a.end - a.start) / W) * 100, 0.8)}%;background:${STAGE_COLORS[a.stage] || "#999"}"></div>${now !== null ? `<div class="g-now" style="left:${(now / W) * 100}%"></div>` : ""}</div></div>`).join("")}</div>`;
  $("#durIn").addEventListener("change", (ev) => saveSettings({ duration_months: Math.max(1, Number(ev.target.value) || 12) }));
  $("#timeSlider").addEventListener("input", (ev) => { const v = Number(ev.target.value); setTime(v >= W ? null : v); });
  $("#timeOff").addEventListener("click", () => { stopPlay(); setTime(null); });
  $("#playBtn").addEventListener("click", () => (S.playing ? stopPlay() : startPlay()));
}
function setTime(t) {
  S.time = t;
  paint();
  // update the panel without stealing the slider drag
  const slider = $("#timeSlider");
  const active = document.activeElement === slider;
  if (!active || S.playing) renderTime();
  else { slider.nextElementSibling.textContent = t === null ? "finished" : "week " + fmt(t, 1); }
}
function startPlay() {
  const W = S.est.schedule.weeks;
  let t = S.time === null || S.time >= W ? 0 : S.time;
  S.playing = setInterval(() => {
    t += W / 120;
    if (t >= W) { stopPlay(); setTime(null); return; }
    setTime(t);
  }, 80);
  renderTime();
}
function stopPlay() { if (S.playing) { clearInterval(S.playing); S.playing = null; if (S.est) renderTime(); } }

// ---------- compare ----------
function renderCompare() {
  const p = S.project, ready = p.versions.filter((v) => v.status === "ready");
  const c = S.compare;
  const opts = (sel) => ready.map((v) => `<option value="${v.id}" ${v.id === sel ? "selected" : ""}>${esc(v.label)} · ${esc(v.file_name || "")}</option>`).join("");
  const prev = ready.length > 1 ? ready[ready.findIndex((v) => v.id === S.version.id) - 1] || ready[0] : null;
  let body = "";
  if (ready.length < 2) {
    body = `<div class="callout">Upload a newer export of the same Revit model to see what changed and how the cost moved. Revit keeps element IDs stable between exports, so every added, removed or changed element is found.</div>`;
  } else if (c) {
    const d = c.total_after - c.total_before;
    body = `
      <div class="kpis">
        <div class="kpi"><span>${esc(c.a.label)} total</span><b>${fmt(c.total_before)}</b></div>
        <div class="kpi"><span>${esc(c.b.label)} total</span><b>${fmt(c.total_after)}</b></div>
        <div class="kpi"><span>Difference</span><b class="${d > 0 ? "pos" : "neg"}">${d > 0 ? "+" : ""}${fmt(d)} ${c.currency}</b></div>
        <div class="kpi"><span>Elements</span><b><span class="tag added">+${c.counts.added || 0}</span> <span class="tag removed">−${c.counts.removed || 0}</span> <span class="tag changed">~${c.counts.changed || 0}</span></b></div>
      </div>
      <h3>By trade</h3>
      <table><thead><tr><th>Trade</th><th class="n">Before</th><th class="n">After</th><th class="n">Change</th></tr></thead><tbody>
      ${c.by_trade.filter((t) => Math.abs(t.delta) > 0.5).map((t) => `<tr><td>${esc(t.trade)}</td><td class="n">${fmt(t.before)}</td><td class="n">${fmt(t.after)}</td><td class="n ${t.delta > 0 ? "pos" : "neg"}">${t.delta > 0 ? "+" : ""}${fmt(t.delta)}</td></tr>`).join("") || '<tr><td colspan="4" class="muted">No cost change.</td></tr>'}
      </tbody></table>
      <h3>Changed elements (${c.rows.length})</h3>
      <table><tbody>${c.rows.slice(0, 300).map((r) => `<tr class="click" data-g="${r.guid}"><td>${esc(r.name)}<br><span class="tag ${r.status}">${r.status}</span> <span class="muted small">${esc(r.why)}</span></td><td class="n ${r.delta > 0 ? "pos" : "neg"}">${r.delta > 0 ? "+" : ""}${fmt(r.delta)}</td></tr>`).join("")}</tbody></table>`;
  }
  $("#tab-compare").innerHTML = `
    <div class="toolbar"><label class="btn primary">Upload new revision<input type="file" id="revFile" accept=".ifc" hidden></label></div>
    ${ready.length >= 2 ? `<div class="toolbar"><select id="cmpA">${opts(c?.a.id || prev?.id)}</select> → <select id="cmpB">${opts(c?.b.id || S.version.id)}</select><button class="btn" id="cmpRun">Compare</button>${c ? '<button class="btn" id="cmpClear">Clear</button>' : ""}</div>` : ""}
    <div class="toolbar"><label class="muted small">Revision name <input type="text" id="verLabel" value="${esc(S.version.label)}" style="width:140px"></label></div>
    ${body}`;
  $("#revFile").addEventListener("change", (ev) => { const f = ev.target.files[0]; if (f) uploadFile(f, p.id); });
  $("#verLabel").addEventListener("change", async (ev) => { await api(`/api/versions/${S.version.id}`, { method: "PATCH", json: { label: ev.target.value } }); S.project = await api(`/api/projects/${p.id}`); S.version = S.project.versions.find((v) => v.id === S.version.id); renderVersions(); });
  $("#cmpRun")?.addEventListener("click", runCompare);
  $("#cmpClear")?.addEventListener("click", () => { S.compare = null; viewer.clearGhosts(); $("#colorMode [data-mode=changes]").hidden = true; setMode("cost"); renderCompare(); });
  $$("tr[data-g]", $("#tab-compare")).forEach((tr) => tr.addEventListener("click", () => { viewer.fit([tr.dataset.g]); S.selected = tr.dataset.g; paint(); }));
}
async function runCompare() {
  const a = $("#cmpA").value, b = $("#cmpB").value;
  if (a === b) return toast("Choose two different revisions.");
  busy(true, "Comparing revisions…");
  try {
    if (b !== S.version.id) { busy(false); toast("Opening the newer revision first…"); go(S.project.id, b); return; }
    const c = await api(`/api/projects/${S.project.id}/compare?a=${a}&b=${b}`);
    S.compare = c;
    if (c.removed.length) viewer.addGhosts(await Viewer.fetchGeometry(a), c.removed);
    else viewer.clearGhosts();
    $("#colorMode [data-mode=changes]").hidden = false;
    setMode("changes");
    renderCompare();
  } catch (err) { toast(err.message); }
  busy(false);
}

// ---------- rates ----------
async function openRates() {
  const region = S.est?.region || $("#region").value;
  const t = await api(`/api/rates/${region}`);
  S.rates = t;
  $("#ratesRegion").textContent = `${S.lib.regions[region].name} · ${t.currency}`;
  $("#rateTemplate").href = `/api/rates/${region}/template.xlsx`;
  $("#ratesDlg").hidden = false;
  drawRates();
}
function drawRates() {
  const t = S.rates, q = ($("#rateSearch").value || "").toLowerCase();
  let trade = null, html = `<table><thead><tr><th>Work item</th><th>Unit</th><th class="n">Base rate (converted)</th><th class="n">Material</th><th class="n">Labour</th><th class="n">Equipment</th><th>Source</th></tr></thead><tbody>`;
  for (const r of t.rows) {
    if (q && !(r.work_item + " " + r.description + " " + r.trade).toLowerCase().includes(q)) continue;
    if (r.trade !== trade) { trade = r.trade; html += `<tr><td colspan="7"><b>${esc(trade)}</b></td></tr>`; }
    const lo = r.local || ["", "", ""];
    html += `<tr data-wi="${r.work_item}" class="${r.local ? "local" : ""}"><td>${esc(r.description)}<br><span class="tag">${r.work_item}</span></td><td>${r.unit}</td>
      <td class="n">${fmt(r.base[0] + r.base[1] + r.base[2], 2)}</td>
      ${[0, 1, 2].map((i) => `<td class="n"><input type="number" step="any" min="0" data-i="${i}" value="${lo[i]}" placeholder="${fmt(r.base[i], 2)}"></td>`).join("")}
      <td><input type="text" data-src value="${esc(r.local ? r.source : "")}" placeholder="${esc(r.source)}"></td></tr>`;
  }
  $("#ratesBody").innerHTML = html + "</tbody></table>";
  $$("#ratesBody tr[data-wi]").forEach((tr) => tr.addEventListener("input", () => {
    const r = S.rates.rows.find((x) => x.work_item === tr.dataset.wi);
    const vals = $$("input[data-i]", tr).map((i) => i.value);
    r.local = vals.some((v) => v !== "") ? vals.map((v) => Number(v) || 0) : null;
    r.source = $("input[data-src]", tr).value;
    tr.classList.toggle("local", !!r.local);
    S.ratesDirty = true;
  }));
}
$("#ratesBtn").addEventListener("click", openRates);
$("#rateSearch").addEventListener("input", drawRates);
$("#rateClose").addEventListener("click", () => {
  if (S.ratesDirty && !confirm("Close without saving your rate changes?")) return;
  S.ratesDirty = false; $("#ratesDlg").hidden = true;
});
$("#rateSave").addEventListener("click", async () => {
  const rows = S.rates.rows.filter((r) => r.local).map((r) => ({ work_item: r.work_item, material: r.local[0], labour: r.local[1], equipment: r.local[2], source: r.source || "user" }));
  try {
    const res = await api(`/api/rates/${S.rates.region}`, { method: "PUT", json: rows });
    S.ratesDirty = false; $("#ratesDlg").hidden = true;
    toast(`Saved ${res.saved} rates.`);
    if (S.project) refresh();
  } catch (err) { toast(err.message); }
});
$("#rateImport").addEventListener("change", async (ev) => {
  const f = ev.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  try {
    const r = await api(`/api/rates/${S.rates.region}/import`, { method: "POST", body: fd });
    toast(`Imported ${r.imported} rows.`);
    S.ratesDirty = false;
    await openRates();
    if (S.project) refresh();
  } catch (err) { toast(err.message); }
  ev.target.value = "";
});

// ---------- misc UI ----------
function tab(name) {
  $$(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("on", t.id === "tab-" + name));
  if (name !== "time" && S.time !== null) { stopPlay(); S.time = null; paint(); }
}
$$(".tabs button").forEach((b) => b.addEventListener("click", () => tab(b.dataset.tab)));
function setMode(m) {
  S.mode = m;
  $$("#colorMode button").forEach((x) => x.classList.toggle("on", x.dataset.mode === m));
  paint();
}
$$("#colorMode button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
$("#levelSel").addEventListener("change", (e) => { S.level = e.target.value; paint(); });
$("#fitBtn").addEventListener("click", () => viewer.fit(S.highlight ? [...S.highlight] : null));
$("#export").addEventListener("click", () => { location.href = `/api/projects/${S.project.id}/export.xlsx?version=${S.version.id}`; });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { S.highlight = null; S.selected = null; $$("tr.sel").forEach((x) => x.classList.remove("sel")); paint(); } });

init().catch((err) => toast(err.message));
