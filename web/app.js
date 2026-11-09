import * as THREE from "three";
import { Viewer } from "./viewer.js";
import { LANGS, applyStatic, getLang, setLang, t } from "./i18n.js";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
// Numbers always use Western digits and the interface language for separators (estimators need consistent figures).
const NUM_LOCALE = () => { try { return (localStorage.getItem("bim5d.lang") || "en") + "-u-nu-latn"; } catch { return "en"; } };
const fmt = (n, d = 0) => (n === null || n === undefined || isNaN(n)) ? "–" : Number(n).toLocaleString(NUM_LOCALE(), { minimumFractionDigits: d, maximumFractionDigits: d });
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const TRADE_COLORS = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2", "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac", "#86bcb6", "#d4a6c8", "#8cd17d", "#f1ce63"];
// Display units: quantities are stored metric; imperial is for display only.
const UNIT = { m: ["ft", 3.28084], m2: ["ft²", 10.7639], m3: ["yd³", 1.30795], kg: ["lb", 2.20462] };
const imperial = () => S.units === "imperial";
function uq(qty, unit) {           // -> [qty, unit] in display units
  const u = UNIT[unit];
  return imperial() && u ? [qty * u[1], u[0]] : [qty, unit === "m2" ? "m²" : unit === "m3" ? "m³" : unit];
}
function ur(rate, unit) {          // rate per display unit
  const u = UNIT[unit];
  return imperial() && u ? rate / u[1] : rate;
}
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
    legend = `<b>${t("Week")} ${fmt(S.time, 1)}</b><div class="key"><span class="sw" style="background:#f59e0b"></span>${t("Being built")}</div><div class="key"><span class="sw" style="background:#9aa4b2"></span>${t("Done")}</div>`;
  } else if (S.mode === "cost") legend = `<div class="ramp"></div><div class="ramp-l"><span>${t("low")}</span><span>${fmt(p95)}+ ${cur()}</span></div>`;
  else if (S.mode === "trade") legend = trades.map((tr, i) => `<div class="key"><span class="sw" style="background:${TRADE_COLORS[i % TRADE_COLORS.length]}"></span>${esc(tx("trade", tr, tr))}</div>`).join("");
  else if (S.mode === "check") legend = `<div class="key"><span class="sw" style="background:#15803d"></span>${t("Priced")}</div><div class="key"><span class="sw" style="background:#f59e0b"></span>${t("Shape needs review")}</div><div class="key"><span class="sw" style="background:#dc2626"></span>${t("Not priced")}</div><div class="key"><span class="sw" style="background:#9aa4b2"></span>${t("Excluded")}</div>`;
  else if (cmp) legend = `<div class="key"><span class="sw" style="background:#16a34a"></span>${t("Added")}</div><div class="key"><span class="sw" style="background:#f59e0b"></span>${t("Changed")}</div><div class="key"><span class="sw" style="background:#dc2626"></span>${t("Removed")}</div>`;
  $("#legend").innerHTML = legend;
  $("#showAll").hidden = !S.highlight;

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
  viewer.redraw();
}

// ---------- start page ----------
async function init() {
  const [lib, samples] = await Promise.all([api("/api/library"), api("/api/samples")]);
  S.lib = lib;
  const regionOpts = Object.entries(lib.regions).map(([k, r]) => `<option value="${k}">${esc(r.name)} (${r.currency})</option>`).join("");
  $("#region").innerHTML = regionOpts;
  $("#startRegion").innerHTML = regionOpts;
  const loc = (navigator.language || "").split("-")[1]?.toUpperCase();
  $("#startRegion").value = localStorageGet("region") || (loc && lib.regions[loc] ? loc : "GLOBAL");
  $("#langSel").innerHTML = Object.entries(LANGS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
  $("#langSel").value = getLang();
  S.units = localStorageGet("units") || "metric";
  $("#unitSel").value = S.units;
  applyStatic();
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
      <div class="meta">${esc(S.lib.regions[p.settings.region]?.name || p.settings.region)} · ${new Date(p.created * 1000).toLocaleDateString(NUM_LOCALE())}</div></div>`;
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

async function uploadFile(file, projectId, discipline) {
  if (!/\.(ifc|ifczip|zip)$/i.test(file.name)) return toast(t("Please choose an .ifc file."));
  const fd = new FormData();
  fd.append("file", file);
  if (projectId) fd.append("project_id", projectId);
  if (discipline) fd.append("discipline", discipline);
  else fd.append("region", $("#startRegion").value);
  busy(true, `${t('Uploading')} ${file.name}…`);
  try {
    const r = await api("/api/projects", { method: "POST", body: fd });
    await loadProjects();
    go(r.project_id, r.version_id || undefined);
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
    // The estimate combines this revision with the latest revision of each other discipline model.
    S.models = await api(`/api/projects/${pid}/models?version=${v.id}`);
    const parts = await Promise.all(S.models.map((m) => Promise.all([Viewer.fetchGeometry(m.id), api(`/api/versions/${m.id}/elements`)])));
    const els = {};
    parts.forEach(([, e], i) => { for (const [g, x] of Object.entries(e)) if (!els[g]) els[g] = { ...x, model: S.models[i].discipline || "" }; });
    S.geo = parts[0][0]; S.els = els;
    viewer.load(parts[0][0]);
    parts.slice(1).forEach(([geo]) => viewer.add(geo, false));
    if (parts.length > 1) viewer.fit();
    p = await api(`/api/projects/${pid}`);
    S.project = p; S.version = p.versions.find((x) => x.id === v.id);
    renderVersions();
    const levels = [...new Set(Object.values(els).map((e) => e.level))].sort();
    $("#levelSel").innerHTML = `<option value="">${t("All levels")}</option>` + levels.map((l) => `<option>${esc(l)}</option>`).join("");
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
  renderSteps(); renderSummary(); renderBoq(); renderMapping(); renderChecks(); renderTime(); renderCompare();
  if (S.selected) renderElement(S.selected);
  paint();
}

async function saveSettings(changes) {
  toast("Updating the estimate…");
  try {
    await api(`/api/projects/${S.project.id}`, { method: "PATCH", json: changes });
    S.project = await api(`/api/projects/${S.project.id}`);
    if (S.compare) S.compare = null;
    await refresh();
    toast("Estimate updated.");
  } catch (err) { toast(err.message); }
}

// ---------- summary ----------
function bars(obj) {
  const vals = Object.values(obj);
  const max = Math.max(...vals, 1);
  return `<div class="bars">${Object.entries(obj).map(([k, v]) => `<div class="bar"><span title="${esc(k)}">${esc(k)}</span><div class="track"><div class="fill" style="width:${(v / max) * 100}%"></div></div><span class="v">${fmt(v)}</span></div>`).join("")}</div>`;
}

// "What to do next": the few actions that improve this estimate most, in plain words.
function nextSteps(e) {
  const c = e.checks, a = e.accuracy, items = [];
  const unpricedTypes = e.groups.filter((g) => g.recipe === null && g.source === "none").length;
  const noRate = (S.project.settings.manual_items || []).filter((m) => Number(m.qty) > 0 && !m.work_item && !Number(m.rate)).length;
  if (noRate) items.push([t("Items measured by hand without a rate: {n}. Choose a work item or type a rate.", { n: noRate }), t("Show list"), "scroll:manualSec"]);
  const gen = c.generic;
  if (gen && gen.share > 0.15) items.push([t("{p}% of the cost is on generic placeholder types ({types}). Choose what they are built of.", { p: Math.round(gen.share * 100), types: gen.types.slice(0, 2).join(", ") }), t("Open Mapping"), "goto:mapping"]);
  if (unpricedTypes) items.push([t("Element types not priced yet: {n}. Tell the tool what they are.", { n: unpricedTypes }), t("Open Mapping"), "goto:mapping"]);
  if ((a.user_price_share || 0) < 0.5) items.push([t("Prices: {a}% assumed, {e}% estimated. Confirm today's prices for labour, ready-mix, rebar, blocks and cement.", { a: Math.round((a.assumed_price_share || 0) * 100), e: Math.round((a.estimated_price_share || 0) * 100) }), t("Enter prices"), "rates"]);
  const gap = e.scope.find((x) => !x.present && x.suggest && !e.allowances.some((al) => al.name === x.suggest.name));
  if (gap) items.push([t("Not in the model: {name}. Add an allowance so the total is complete.", { name: tx("scope", gap.name, gap.name) }), t("Add {v}% allowance", { v: gap.suggest.value }), "allow:" + JSON.stringify(gap.suggest)]);
  if (c.duplicates.length) items.push([t("Elements that look duplicated: {n}. Check them before issuing.", { n: c.duplicates.length }), t("Open Checks"), "goto:checks"]);
  else if (c.overlaps.length) items.push([t("Overlaps found and counted once: {n}. Have a quick look.", { n: c.overlaps.length }), t("Open Checks"), "goto:checks"]);
  const missing = e.checklist.filter((x) => x.status === "missing").length;
  if (missing) items.push([t("Commonly forgotten items not covered: {n}.", { n: missing }), t("Show list"), "scroll:scope"]);
  items.push([t("When you are happy, send the client report or the Excel workbook."), t("Client report"), "report"]);
  return `<div class="next"><b>${t("What to do next")}</b><ol>${items.slice(0, 5).map(([txt, btn, act]) =>
    `<li><span dir="auto">${esc(txt)}</span> <button class="btn sm" data-next='${esc(act)}'>${esc(btn)}</button></li>`).join("")}</ol></div>`;
}

// The six steps an estimator goes through, with their status.
function steps() {
  const e = S.est, c = e.checks;
  const unpriced = c.unclassified.length;
  const sample = e.accuracy.sample_rate_share;
  const gaps = e.scope.filter((x) => !x.present && x.suggest && !e.allowances.some((a) => a.name === x.suggest.name)).length;
  const rec = c.reconciliation;
  const issues = c.duplicates.length + c.geometry_flagged.length + (rec.share !== null && rec.share < 0.95 ? 1 : 0);
  return [
    { n: 1, label: t("Model"), tab: "summary", ok: true, tip: `${fmt(c.elements)} elements measured` },
    { n: 2, label: t("Map"), tab: "mapping", ok: !unpriced, tip: unpriced ? `${unpriced} elements not priced` : "All elements priced" },
    { n: 3, label: t("Rates"), tab: "rates", ok: (e.accuracy.user_price_share || 0) >= 0.5, tip: `${Math.round((e.accuracy.user_price_share || 0) * 100)}% your prices, ${Math.round((e.accuracy.assumed_price_share || 0) * 100)}% assumed, ${Math.round((e.accuracy.estimated_price_share || 0) * 100)}% estimated` },
    { n: 4, label: t("Scope"), tab: "summary#scope", ok: !gaps, tip: gaps ? `${gaps} missing parts without allowance` : "Scope covered" },
    { n: 5, label: t("Check"), tab: "checks", ok: !issues, tip: issues ? "Review overlaps, duplicates and outliers" : "No issues found" },
    { n: 6, label: t("Report"), tab: "report", ok: false, tip: "Client report and Excel" },
  ];
}
function renderSteps() {
  $("#steps").innerHTML = steps().map((s) => `<button class="step ${s.ok ? "done" : ""}" data-step="${s.tab}" title="${esc(s.tip)}"><span class="num">${s.ok ? "✓" : s.n}</span>${s.label}</button>`).join("");
  $$("#steps [data-step]").forEach((b) => b.addEventListener("click", () => {
    const t = b.dataset.step;
    if (t === "rates") return openRates();
    if (t === "report") return openReport();
    const [tb, anchor] = t.split("#");
    tab(tb);
    if (anchor) $("#" + anchor)?.scrollIntoView({ behavior: "smooth" });
  }));
}

function renderSummary() {
  const e = S.est, s = e.summary, c = e.checks, st = S.project.settings, reg = S.lib.regions[e.region];
  const a = e.accuracy;
  const row = (label, v, cls = "") => v ? `<tr class="${cls}"><td>${label}</td><td class="n">${fmt(v)}</td></tr>` : "";
  let bench = "";
  if (s.per_m2 && s.benchmark) {
    const b = s.benchmark, inside = s.per_m2 >= b.low && s.per_m2 <= b.high;
    bench = `<div class="callout ${inside ? "ok" : ""}">${t("Cost per m²")}: <b>${fmt(s.per_m2)} ${e.currency}</b> ${t("on {a} m² floor area.", { a: fmt(s.gfa) })} ${t("Typical for")} <i dir="auto">${esc(b.factor && b.factor !== 1 ? `${t(b.type_label)}: ${b.factor} × ${t(b.base_label)} (${t("assumed ratio")})` : t(b.label))}</i>: ${fmt(b.low)}–${fmt(b.high)}. ${inside ? t("Inside the usual range.") : s.per_m2 < b.low ? t("Lower than usual: check the scope list below for parts not in the model.") : t("Higher than usual: check rates and quantities.")}</div>`;
  }
  const lv = Object.entries(s.gfa_by_level || {});
  if (lv.length > 1 || s.gfa_warning) bench += `<details class="small gfa-lv"><summary>${t("Floor area by level")}: ${fmt(s.gfa)} m²${s.gfa_warning ? ' <span class="bad">⚠</span>' : ""}</summary>
    ${s.gfa_warning ? `<p class="bad" dir="auto">${esc(s.gfa_warning)}</p>` : ""}<table>${lv.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="n">${fmt(v)} m²</td></tr>`).join("")}</table>
    <p class="muted">${t("Each level counts once: the larger of its floor slabs, floor build-ups or rooms. Levels with nothing built on them (roof) are not counted. Type your own total in Project settings.")}</p></details>`;
  const rb = c.rebar;
  const rebarNote = (rb.modeled_kg > 0) ? `<div class="callout">${t("Rebar: modelled bars {a} kg, ratios give {b} kg. Using {m}.", { a: `<b>${fmt(rb.modeled_kg)}</b>`, b: `<b>${fmt(rb.ratio_kg)}</b>`, m: `<b>${t(rb.mode === "modeled" ? "modelled bars" : "ratios")}</b>` })}${rb.modeled_kg < rb.ratio_kg * 0.5 ? " " + t("The modelled rebar looks incomplete.") : ""}</div>` : "";
  const scopeRows = e.scope.map((x) => {
    const added = x.suggest && e.allowances.some((al) => al.name === x.suggest.name);
    return `<tr><td>${x.present ? '<span class="ok">✓</span>' : '<span class="bad">✗</span>'} ${esc(tx("scope", x.name, x.name))}</td><td class="n">${x.present ? fmt(x.cost) : ""}</td>
      <td>${!x.present && x.suggest ? (added ? `<span class="tag">${t("allowance added")}</span>` : `<button class="btn sm" data-allow='${esc(JSON.stringify(x.suggest))}'>${t("Add {v}% allowance", { v: x.suggest.value })}</button>`) : (x.present ? "" : `<span class="muted small">${t("not in model")}</span>`)}</td></tr>`;
  }).join("");
  const allowRows = (st.allowances || []).map((al, i) => {
    const calc = e.allowances[i]?.amount;
    return `<tr><td><input type="text" data-al="${i}" data-f="name" value="${esc(al.name)}"></td>
      <td><select data-al="${i}" data-f="kind"><option value="pct" ${al.kind === "pct" ? "selected" : ""}>${t("% of measured")}</option><option value="lump" ${al.kind === "lump" ? "selected" : ""}>${t("Lump sum")}</option><option value="per_m2" ${al.kind === "per_m2" ? "selected" : ""}>${t("per m\u00b2")}</option></select></td>
      <td><input type="number" step="any" data-al="${i}" data-f="value" value="${al.value}"></td><td class="n">${fmt(calc)}</td>
      <td><button class="btn sm" data-alrm="${i}" title="Remove">×</button></td></tr>`;
  }).join("");
  const missingCount = e.scope.filter((x) => !x.present && x.suggest && !e.allowances.some((al) => al.name === x.suggest.name)).length
    + e.checklist.filter((x) => x.status === "missing").length;
  const gapsOpen = missingCount > 0;
  // Keep the sections the user opened or closed, and the scroll position, when the summary redraws.
  const host = $("#tab-summary");
  const wasOpen = S._sumPid === S.project.id ? $$("details.sec", host).map((d) => d.open) : [];
  const scrollers = [];
  for (let n = host; n; n = n.parentElement) if (n.scrollTop) scrollers.push([n, n.scrollTop]);
  S._sumPid = S.project.id;
  host.innerHTML = `
    <div class="muted">${esc(S.project.name)} · ${(e.models || []).length > 1 ? e.models.map((m) => esc(m.label)).join(" + ") : esc(S.version.label)} · ${esc(e.region_name)}</div>
    <div class="total">${fmt(s.total)} <small>${e.currency}</small></div>
    <div class="acc acc${a.class}"><b dir="auto">${esc(t(a.label))}</b> · ${t("likely between")} <b>${fmt(a.low)}</b> ${t("and")} <b>${fmt(a.high)}</b> ${e.currency} (${Math.round(a.low_pct * 100)}% / +${Math.round(a.high_pct * 100)}%)
      ${a.reasons.length ? `<ul>${(a.reasons_t || a.reasons.map((r) => [r, {}])).map(([tpl, v]) => `<li dir="auto">${esc(t(tpl, v.items ? { ...v, items: v.items.split(", ").map((x) => tx("scope", x, x)).join("، ") } : v))}</li>`).join("")}</ul>` : ""}</div>
    ${nextSteps(e)}
    <h3>${t("Cost build-up")} (${e.currency})</h3>
    <table class="build">
      ${row(t("Measured work (from the model)"), s.direct)}
      ${row(t("Allowances (work not modelled)"), s.allowances)}
      ${row(`${t("Preliminaries")} ${s.prelims_pct}%`, s.prelims)}
      ${row(`${t("Contingency")} ${s.contingency_pct}%`, s.contingency)}
      ${row(`${t("Overhead")} ${s.overhead_pct}%`, s.overhead)}
      ${row(`${t("Profit")} ${s.profit_pct}%`, s.profit)}
      ${row(`${t("Escalation")} ${s.escalation_pct}%`, s.escalation)}
      ${row(`${esc(s.tax_name)} ${s.tax_pct}%`, s.tax)}
      <tr class="tot"><td>${t("Total")}</td><td class="n">${fmt(s.total)}</td></tr>
    </table>
    ${c.unclassified.length ? `<div class="callout">${t("{n} elements have no price yet.", { n: fmt(c.unclassified.length) })} <a href="#" data-goto="mapping">${t("Open Mapping")}</a>.</div>` : ""}
    ${bench}${rebarNote}
    <details class="sec" id="scope" ${gapsOpen ? "open" : ""}><summary>${t("Scope check: is the whole building in the model?")} <span class="muted small">${missingCount ? t("{n} to look at", { n: missingCount }) : t("all covered")}</span></summary>
    <table>${scopeRows}</table>
    <h3>${t("Commonly forgotten items")}</h3>
    <table class="check">${e.checklist.map((c) => `<tr><td>${c.status === "priced" ? '<span class="ok">✓</span>' : c.status === "allowance" ? '<span class="ok">≈</span>' : c.status === "note" ? '<span class="muted">i</span>' : '<span class="bad">✗</span>'} ${esc(tx("check", c.name, c.name))}</td>
      <td class="n">${c.cost ? fmt(c.cost) : ""}</td>
      <td>${c.status === "missing" && c.suggest ? `<button class="btn sm" data-allow='${esc(JSON.stringify(c.suggest))}'>${t("Add")} ${c.suggest.value}%</button>` : c.note ? `<span class="muted small">${esc(t(c.note))}</span>` : c.status === "missing" ? `<span class="muted small">${t("missing")}</span>` : `<span class="muted small">${t(c.status)}</span>`}</td></tr>`).join("")}</table>
    </details>
    <details class="sec" id="manualSec" ${(st.manual_items || []).length || (st.allowances || []).length ? "open" : ""}><summary>${t("Items measured by hand (not in the model)")} &amp; ${t("Allowances for work not in the model").toLowerCase()} <span class="muted small">${fmt(s.allowances + e.lines.filter((l) => l.recipe === "MANUAL").reduce((x, l) => x + l.amount, 0))} ${e.currency}</span></summary>
    <h3>${t("Items measured by hand (not in the model)")}</h3>
    <p class="muted small">${t("Like a virtual takeoff: boundary walls, external works, anything not modelled. Pick a work item to use its rate, or type your own rate.")}</p>
    ${(st.manual_items || []).length ? `<table class="allow"><thead><tr><th>${t("Description")}</th><th>${t("Work item")}</th><th>${t("Qty")}</th><th>${t("Unit")}</th><th>${t("Rate")}</th><th></th></tr></thead><tbody>${(st.manual_items || []).map((m, i) => `<tr>
      <td><input type="text" data-mi="${i}" data-f="description" value="${esc(m.description || "")}"></td>
      <td><select data-mi="${i}" data-f="work_item"><option value="">— ${t("own rate")} —</option>${Object.entries(S.lib.work_items).map(([k, w]) => `<option value="${k}" ${k === m.work_item ? "selected" : ""}>${esc(w.description)}</option>`).join("")}</select></td>
      <td><input type="number" step="any" data-mi="${i}" data-f="qty" value="${m.qty ?? ""}"></td>
      <td><input type="text" data-mi="${i}" data-f="unit" value="${esc(m.unit || "")}" style="width:50px"></td>
      <td><input type="number" step="any" data-mi="${i}" data-f="rate" value="${m.rate ?? ""}" placeholder="${t("auto")}"></td>
      <td><button class="btn sm" data-mirm="${i}">×</button></td></tr>`).join("")}</tbody></table>` : ""}
    <button class="btn sm" id="addManual">+ ${t("Add item")}</button>
    <h3>${t("Allowances for work not in the model")}</h3>
    ${allowRows ? `<table class="allow"><thead><tr><th>${t("Item")}</th><th>${t("Basis")}</th><th>${t("Value")}</th><th class="n">${t("Amount")}</th><th></th></tr></thead><tbody>${allowRows}</tbody></table>` : `<p class="muted small">${t("None yet.")}</p>`}
    <button class="btn sm" id="addAllow">+ ${t("Add allowance")}</button>
    </details>
    <details class="sec" open><summary>${t("By trade")} &amp; ${t("Elemental cost plan").toLowerCase()}</summary>
    <h3>${t("By trade")} (${e.currency})</h3>${bars(Object.fromEntries(Object.entries(e.by_trade).map(([k, v]) => [tx("trade", k, k), v])))}
    <h3>${t("Elemental cost plan")}</h3>
    <div class="seg" id="planSeg" style="display:inline-flex;margin-bottom:6px"><button data-plan="by_nrm1" class="on">NRM1</button><button data-plan="by_uniformat">Uniformat</button><button data-plan="by_level">${t("Level")}</button></div>
    <div id="planBars">${bars(Object.fromEntries(Object.entries(e.by_nrm1).map(([k, v]) => [tx("nrm1", k, k), v])))}</div>
    </details>
    <details class="sec"><summary>${t("Project settings")} <span class="muted small">${t("mark-ups, measurement rules, rebar, furniture")}</span></summary>
    <div class="settings">
      <label>${t("Building type")}<select data-set="building_type">${Object.entries(S.lib.building_types || {}).map(([k, v]) => `<option value="${k}" ${k === (st.building_type || "residential") ? "selected" : ""}>${esc(t(v))}</option>`).join("")}</select></label>
      <label>${t("Preliminaries")} %<input type="number" step="0.5" min="0" data-set="prelims_pct" value="${st.prelims_pct ?? reg.prelims_pct ?? 10}"></label>
      <label>${t("Contingency")} %<input type="number" step="0.5" min="0" data-set="contingency_pct" value="${st.contingency_pct ?? reg.contingency_pct}"></label>
      <label>${t("Overhead")} %<input type="number" step="0.5" min="0" data-set="overhead_pct" value="${st.overhead_pct ?? reg.overhead_pct}"></label>
      <label>${t("Profit")} %<input type="number" step="0.5" min="0" data-set="profit_pct" value="${st.profit_pct ?? reg.profit_pct}"></label>
      <label>${t("Escalation")} %<input type="number" step="0.5" min="0" data-set="escalation_pct" value="${st.escalation_pct ?? reg.escalation_pct ?? 0}" title="${esc(reg.escalation_note || "")}"></label>
      <label>${esc(reg.tax_name)} %<input type="number" step="0.5" min="0" data-set="tax_pct" value="${st.tax_pct ?? reg.tax_pct}"></label>
      <label>${t("Measurement standard")}<select data-set="standard">${Object.entries(S.lib.standards).map(([k, v]) => `<option value="${k}" ${k === e.standard.code ? "selected" : ""}>${esc(t(v))}</option>`).join("")}</select></label>
      <label>${t("Wall and ceiling finishes from")}<select data-set="finishes_from"><option value="auto" ${(st.finishes_from || "auto") === "auto" ? "selected" : ""}>${t("Automatic (rooms if the model has them)")}</option><option value="rooms" ${st.finishes_from === "rooms" ? "selected" : ""}>${t("Rooms (room perimeter x height)")}</option><option value="walls" ${st.finishes_from === "walls" ? "selected" : ""}>${t("Walls (both faces)")}</option></select></label>
      <label>${t("Rebar based on")}<select data-set="rebar_mode"><option value="ratio">${t("Ratios (kg per m³)")}</option><option value="modeled">${t("Modelled rebar bars")}</option></select></label>
      <label>${t("Don't deduct openings up to (m²)")}<input type="number" step="0.1" min="0" data-set="min_deduct_m2" value="${st.min_deduct_m2 ?? 0.5}"></label>
      <label>${t("Floor area for cost/m² (blank = from slabs)")}<input type="number" step="1" min="0" data-set="gfa_m2" value="${st.gfa_m2 ?? ""}" placeholder="${fmt(s.gfa)}"></label>
      <label>${t("Project name")}<input type="text" data-set="name" value="${esc(S.project.name)}"></label>
      <label class="check"><input type="checkbox" data-set="deduct_overlaps" ${st.deduct_overlaps !== false ? "checked" : ""}> ${t("Deduct overlaps between elements")}</label>
      <label class="check"><input type="checkbox" data-set="include_loose_ffe" ${st.include_loose_ffe ? "checked" : ""}> ${t("Include loose furniture")}${s.ffe_count ? ` (${s.ffe_count} items, ${fmt(s.ffe_outside)} ${e.currency})` : ""}</label>
      <a class="btn sm" href="/api/projects/${S.project.id}/package.zip" style="grid-column: span 2; justify-self: start">${t("Download project file (to send to a colleague)")}</a>
      <label class="check"><input type="checkbox" data-set="rates_verified" ${st.rates_verified ? "checked" : ""}> ${t("Rates checked against current market prices")}</label>
    </div>
    </details>
    <details class="sec"><summary>${t("Assumptions")} &amp; ${t("Exclusions").toLowerCase()} <span class="muted small">${t("shown in the client report")}</span></summary>
    <h3>${t("Assumptions")}</h3><ul class="small">${(e.assumptions_t || e.assumptions.map((x) => [x, {}])).map(([tpl, v]) => `<li dir="auto">${esc(t(tpl, Object.fromEntries(Object.entries(v).map(([k, x]) => [k, t(x)]))))}</li>`).join("")}</ul>
    <h3>${t("Exclusions")}</h3>
    <textarea id="exclusions" rows="6" class="full">${esc(e.exclusions.filter((x) => !x.endsWith("(not in the model)")).join("\n"))}</textarea>
    <p class="muted small">${t("One per line. Saved when you click outside the box.")}</p>
    </details>`;
  $$("details.sec", host).forEach((d, i) => { if (i < wasOpen.length) d.open = wasOpen[i]; });
  scrollers.forEach(([n, top]) => (n.scrollTop = top));
  $("[data-set=rebar_mode]").value = st.rebar_mode || "ratio";
  $$("[data-set]", $("#tab-summary")).forEach((inp) => inp.addEventListener("change", () => {
    const k = inp.dataset.set;
    const v = inp.type === "checkbox" ? inp.checked : inp.type === "number" ? (inp.value === "" ? null : Number(inp.value)) : inp.value;
    saveSettings({ [k]: v });
  }));
  $$("#planSeg button").forEach((b) => b.addEventListener("click", () => {
    $$("#planSeg button").forEach((x) => x.classList.toggle("on", x === b));
    const plan = S.est[b.dataset.plan];
    $("#planBars").innerHTML = bars(b.dataset.plan === "by_nrm1" ? Object.fromEntries(Object.entries(plan).map(([k, v]) => [tx("nrm1", k, k), v])) : plan);
  }));
  $$("[data-goto]", $("#tab-summary")).forEach((x) => x.addEventListener("click", (ev) => { ev.preventDefault(); tab(x.dataset.goto); }));
  $$("[data-next]", $("#tab-summary")).forEach((b) => b.addEventListener("click", () => {
    const act = b.dataset.next;
    if (act.startsWith("goto:")) return tab(act.slice(5));
    if (act === "rates") return openRates(e.region, "prices");
    if (act === "report") return openReport();
    if (act.startsWith("scroll:")) { const d = $("#" + act.slice(7)); d.open = true; return d.scrollIntoView({ behavior: "smooth" }); }
    if (act.startsWith("allow:")) { const l = JSON.parse(JSON.stringify(S.project.settings.allowances || [])); l.push(JSON.parse(act.slice(6))); return saveSettings({ allowances: l }); }
  }));
  const allows = () => JSON.parse(JSON.stringify(S.project.settings.allowances || []));
  $$("[data-allow]", $("#tab-summary")).forEach((b) => b.addEventListener("click", () => { const l = allows(); l.push(JSON.parse(b.dataset.allow)); saveSettings({ allowances: l }); }));
  $("#addAllow").addEventListener("click", () => { const l = allows(); l.push({ name: "New allowance", kind: "lump", value: 0 }); saveSettings({ allowances: l }); });
  $$("[data-alrm]", $("#tab-summary")).forEach((b) => b.addEventListener("click", () => { const l = allows(); l.splice(Number(b.dataset.alrm), 1); saveSettings({ allowances: l }); }));
  $$("[data-al]", $("#tab-summary")).forEach((inp) => inp.addEventListener("change", () => {
    const l = allows(); const i = Number(inp.dataset.al);
    l[i][inp.dataset.f] = inp.dataset.f === "value" ? Number(inp.value) || 0 : inp.value;
    saveSettings({ allowances: l });
  }));
  $("#exclusions").addEventListener("change", (ev) => saveSettings({ exclusions: ev.target.value.split("\n").map((x) => x.trim()).filter(Boolean) }));
  const manual = () => JSON.parse(JSON.stringify(S.project.settings.manual_items || []));
  $("#addManual").addEventListener("click", () => { const l = manual(); l.push({ description: t("New item"), qty: 1, unit: "item", rate: null, work_item: "" }); saveSettings({ manual_items: l }); });
  $$("[data-mirm]", $("#tab-summary")).forEach((b) => b.addEventListener("click", () => { const l = manual(); l.splice(Number(b.dataset.mirm), 1); saveSettings({ manual_items: l }); }));
  $$("[data-mi]", $("#tab-summary")).forEach((inp) => inp.addEventListener("change", () => {
    const l = manual(), i = Number(inp.dataset.mi), f = inp.dataset.f;
    l[i][f] = (f === "qty" || f === "rate") ? (inp.value === "" ? null : Number(inp.value)) : inp.value;
    if (f === "work_item" && inp.value) { l[i].unit = S.lib.work_items[inp.value]?.unit || l[i].unit; l[i].rate = null; }
    saveSettings({ manual_items: l });
  }));
}

// ---------- checks ----------
async function renderChecks() {
  const e = S.est, c = e.checks, rec = c.reconciliation;
  const name = (g) => esc(S.els[g]?.name || g);
  const methods = { 1: "rough estimate from bounding box", 3: "taken from the model's own volume" };
  const est = c.geometry_flagged.map((g) => `<tr class="click" data-g="${g}"><td>${name(g)}<br><span class="muted small">${methods[S.els[g]?.qty.check] || ""}</span></td></tr>`).join("");
  const overl = [...c.overlaps].sort((x, y) => y.volume - x.volume).slice(0, 150).map((o) => `<tr class="click" data-pair="${o.a},${o.b}"><td>${name(o.a)}<br>${name(o.b)}</td><td class="n">${fmt(o.volume, 3)} m³</td><td class="small">${o.kind === "same type" ? `<span class="tag changed">${t("duplicate?")}</span>` : o.kind === "in two models" ? `<span class="tag changed">${t("in two models")}</span>` : o.kind === "same room shape" ? `<span class="tag changed">${t("same room twice")}</span>` : ""} ${t("from")} <b>${esc((S.els[o.loser]?.kind || "").replace("Ifc", ""))}</b></td></tr>`).join("");
  const outl = rec.outliers.map((r) => `<tr class="click" data-g="${r.guid}"><td>${name(r.guid)}</td><td class="n">${fmt(r.measured, 3)}</td><td class="n">${fmt(r.authored, 3)}</td><td class="n ${Math.abs(r.diff_pct) > 20 ? "bad" : ""}">${r.diff_pct > 0 ? "+" : ""}${r.diff_pct}%</td></tr>`).join("");
  $("#tab-checks").innerHTML = `
    <p class="muted">${t("A senior estimator never trusts model quantities blindly. These checks show where the model needs a look before the estimate is issued.")}</p>
    <h3>1 · ${t("Quantities vs the model's own values")}</h3>
    ${rec.compared ? `<div class="callout ${rec.share >= 0.95 ? "ok" : ""}">${t("{a} of {b} element volumes ({p}%) agree within 5% with the volumes Revit calculated.", { a: rec.within_5pct, b: rec.compared, p: Math.round(rec.share * 100) })}</div>
      ${outl ? `<table><thead><tr><th>${t("Element")}</th><th class="n">${t("Measured m³")}</th><th class="n">${t("Revit m³")}</th><th class="n">${t("Diff")}</th></tr></thead><tbody>${outl}</tbody></table>` : ""}` : `<p class="muted">${t("The model has no volumes of its own to compare with.")}</p>`}
    <h3>2 · ${t("Overlaps")} (${c.overlaps.length}, ${fmt(c.overlap_m3, 2)} m³)</h3>
    <p class="muted small">${e.settings.deduct_overlaps ? t("Shared volume is deducted once, from the element that normally stops at the other (column under slab, beam below slab, wall between frame). Steel keeps its weight.") : t("Overlaps are NOT being deducted (see settings).")} ${c.duplicates.length ? `<b class="bad">${t("Possible duplicates: {n}. Same element twice, in one model or in two models.", { n: c.duplicates.length })}</b>` : ""}</p>
    ${overl ? `<table><tbody>${overl}</tbody></table>` : `<p class="muted">${t("No overlaps found.")}</p>`}
    <h3>3 · ${t("Shapes that could not be measured exactly")} (${c.geometry_flagged.length})</h3>
    ${est ? `<table><tbody>${est}</tbody></table>` : `<p class="muted">${t("None.")}</p>`}
    <h3>4 · ${t("Not priced")} (${c.unclassified.length}) · ${t("excluded")} (${c.excluded.length})</h3>
    <p class="muted small"><a href="#" data-goto="mapping">${t("Open Mapping")}</a></p>
    <h3>5 · ${t("Change history")}</h3><div id="historyBox" class="muted small">…</div>`;
  $$("tr[data-g]", $("#tab-checks")).forEach((tr) => tr.addEventListener("click", () => { viewer.fit([tr.dataset.g]); select(tr.dataset.g, false); }));
  $$("tr[data-pair]", $("#tab-checks")).forEach((tr) => tr.addEventListener("click", () => { const g = tr.dataset.pair.split(","); S.highlight = new Set(g); viewer.fit(g); paint(); }));
  $$("[data-goto]", $("#tab-checks")).forEach((x) => x.addEventListener("click", (ev) => { ev.preventDefault(); tab(x.dataset.goto); }));
  try {
    const h = await api(`/api/projects/${S.project.id}/history`);
    $("#historyBox").innerHTML = h.length ? `<table>${h.slice(0, 60).map((r) => `<tr><td class="small">${new Date(r.time * 1000).toLocaleString(NUM_LOCALE())}</td><td class="small"><b>${esc(r.what)}</b> ${esc(r.detail)}</td></tr>`).join("")}</table>` : t("No changes yet.");
  } catch { $("#historyBox").textContent = ""; }
}

function openReport() {
  // Picture of the whole building coloured by cost, then put the view back.
  const keep = { pos: viewer.camera.position.clone(), target: viewer.controls.target.clone(),
                 mode: S.mode, hl: S.highlight, sel: S.selected, time: S.time, level: S.level };
  S.mode = "cost"; S.highlight = null; S.selected = null; S.time = null; S.level = "";
  viewer.fit(); paint(); viewer.controls.update(); viewer.renderer.render(viewer.scene, viewer.camera);
  try { localStorage.setItem("bim5d.snapshot", viewer.renderer.domElement.toDataURL("image/jpeg", 0.85)); } catch { /* ignore */ }
  Object.assign(S, { mode: keep.mode, highlight: keep.hl, selected: keep.sel, time: keep.time, level: keep.level });
  viewer.camera.position.copy(keep.pos); viewer.controls.target.copy(keep.target); paint();
  window.open(`/report.html#p=${S.project.id}&v=${S.version.id}`, "_blank");
}

// ---------- BOQ ----------
function renderBoq() {
  const e = S.est;
  const seg = `<div class="seg" id="boqSeg" style="display:inline-flex;margin-bottom:8px"><button data-v="items" class="${S.boqView !== "res" ? "on" : ""}">${t("Work items")}</button><button data-v="res" class="${S.boqView === "res" ? "on" : ""}">${t("Resources (materials, labour, plant)")}</button></div>`;
  if (S.boqView === "res") {
    const kindTag = (k) => k === "yours" ? `<span class="tag added">${t("your price")}</span>` : k === "assumed" ? `<span class="tag changed">${t("assumed")}</span>` : `<span class="tag">${t("estimated")}</span>`;
    $("#tab-boq").innerHTML = seg + `<p class="muted">${t("Total labour, materials and plant behind the rates: for ordering, planning and seeing which prices matter most. \"+10%\" shows what a 10% price rise of that resource adds.")}</p>
      <table><thead><tr><th>${t("Resource")}</th><th class="n">${t("Quantity")}</th><th class="n">${t("Cost")}</th><th class="n">${t("Share")}</th><th class="n">+10%</th></tr></thead><tbody>
      ${e.resources.map((r) => `<tr><td><span dir="auto">${esc(tx("resource", r.resource, r.name))}</span> ${kindTag(r.kind)}</td><td class="n">${fmt(r.qty, r.qty < 100 ? 1 : 0)} ${esc(r.unit)}</td><td class="n">${fmt(r.cost)}</td><td class="n">${(r.share * 100).toFixed(1)}%</td><td class="n">${fmt(r.cost * 0.1)}</td></tr>`).join("")}
      </tbody></table>`;
    $$("#boqSeg button").forEach((b) => b.addEventListener("click", () => { S.boqView = b.dataset.v; renderBoq(); }));
    return;
  }
  let html = seg + `<p class="muted">${t("Click a row to highlight its elements in 3D.")}</p><table><thead><tr><th>${t("Item")}</th><th class="n">${t("Qty")}</th><th class="n">${t("Rate")}</th><th class="n">${t("Amount")}</th></tr></thead><tbody>`;
  let trade = null;
  for (const b of e.boq) {
    if (b.trade !== trade) { trade = b.trade; html += `<tr><td colspan="4"><b>${esc(tx("trade", trade, trade))}</b></td></tr>`; }
    const local = tx("work_item", b.work_item, "");
    html += `<tr class="click" data-wi="${b.work_item}"><td>${local ? `<span dir="auto">${esc(local)}</span><br><span class="muted small" dir="ltr">${esc(b.description)}</span>` : esc(b.description)}<br><span class="tag">${b.work_item}</span> <span class="muted small" dir="auto">${t("{n} elements", { n: b.elements })}</span>${String(b.rate_source).startsWith("SAMPLE") ? ' <span class="tag">sample rate</span>' : ""}</td>
      <td class="n">${fmt(uq(b.qty, b.unit)[0], 2)} ${uq(b.qty, b.unit)[1]}</td><td class="n">${fmt(ur(b.rate, b.unit), 2)}</td><td class="n">${fmt(b.amount)}</td></tr>`;
  }
  html += `</tbody><tfoot><tr><th>${t("Direct cost")}</th><th></th><th></th><th class="n">${fmt(e.summary.direct)}</th></tr></tfoot></table>`;
  $("#tab-boq").innerHTML = html;
  $$("#boqSeg button").forEach((b) => b.addEventListener("click", () => { S.boqView = b.dataset.v; renderBoq(); }));
  $$("tr[data-wi]", $("#tab-boq")).forEach((tr) => tr.addEventListener("click", () => {
    const on = tr.classList.contains("sel");
    $$("tr.sel", $("#tab-boq")).forEach((x) => x.classList.remove("sel"));
    if (on) S.highlight = null;
    else { tr.classList.add("sel"); S.highlight = new Set(e.lines.filter((l) => l.work_item === tr.dataset.wi).map((l) => l.guid)); viewer.fit([...S.highlight]); }
    paint();
  }));
}

// ---------- Mapping ----------
// Name of a work item, recipe or trade in the interface language (data/translations.csv), or English.
const tx = (kind, code, english) => S.lib?.translations?.[getLang()]?.[`${kind}:${code}`] || english;
const recipeLabel = (n) => n === "EXCLUDE" ? t("Do not price (exclude)") : tx("recipe", n, S.lib.recipes[n]?.label || n);
function recipeOptions(selected) {
  const names = Object.keys(S.lib.recipes).sort((a, b) => recipeLabel(a).localeCompare(recipeLabel(b)));
  return `<option value="">— ${t("choose")} —</option>` + names.map((n) => `<option value="${n}" ${n === selected ? "selected" : ""}>${esc(recipeLabel(n))}</option>`).join("") +
    `<option value="EXCLUDE" ${selected === "EXCLUDE" ? "selected" : ""}>${t("Do not price (exclude)")}</option>`;
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
    <p class="muted">${t("Each row is one element type. Pick what it is and every element of that type is priced that way. Your choice overrides the automatic rules for this project.")}</p>
    <div class="toolbar">
      <div class="seg" id="mapSeg"><button data-f="unpriced">${t("Not priced")} (${unpricedCount})</button><button data-f="all">${t("All types")} (${e.groups.length})</button><button data-f="manual">${t("Changed by you")}</button></div>
      <input type="search" id="mapSearch" placeholder="${t("Search types")}" value="${esc(S.mapSearch)}">
    </div>
    ${S.lib.ai && unpricedCount ? `<div class="toolbar"><button class="btn" id="aiBtn">${t("Suggest with AI")}</button>${anySugg ? `<button class="btn" id="aiAccept">${t("Accept all suggestions with 80%+ confidence")}</button>` : ""}<span class="muted small">${t("Suggestions are shown for you to check, never applied automatically.")}</span></div>` : ""}
    ${!S.lib.ai && unpricedCount ? `<p class="muted small">${t("Tip: set ANTHROPIC_API_KEY on the server to get AI suggestions for unknown types, including names in other languages.")}</p>` : ""}
    <table><thead><tr><th>${t("Element type")}</th><th class="n">${t("Count")}</th><th class="n">${t("Cost")}</th><th style="width:170px">${t("Priced as")}</th></tr></thead><tbody>
    ${groups.slice(0, 400).map((g) => {
      const sel = maps[g.key] || g.recipe || "";
      const sug = S.suggestions[g.key];
      return `<tr class="map-row click" data-key="${esc(g.key)}"><td>${esc(g.type || "(no name)")}<br><span class="tag">${esc(g.kind.replace(/^Ifc/, ""))}</span> <span class="tag ${g.source}">${t({ rule: "auto rule", mapping: "set by you", none: "no match", excluded: "excluded" }[g.source])}</span>
        ${sug ? `<div class="sugg">AI: <b>${esc(recipeLabel(sug.recipe))}</b> (${Math.round(sug.confidence * 100)}%). ${esc(sug.reason)} <button class="btn sm" data-accept="${esc(g.key)}">${t("Accept")}</button></div>` : ""}</td>
        <td class="n">${g.count}</td><td class="n">${fmt(g.total)}</td>
        <td><select data-map="${esc(g.key)}">${recipeOptions(sel)}</select>${g.source === "mapping" || g.source === "excluded" ? `<button class="btn sm" data-reset="${esc(g.key)}" title="${t("Go back to the automatic rule")}">${t("Reset")}</button>` : ""}</td></tr>`;
    }).join("") || `<tr><td colspan="4" class="muted">${S.mapFilter === "unpriced" ? t("Every element type is priced.") + " 🎉" : t("Nothing found.")}</td></tr>`}
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
  if (!el) { $("#tab-element").innerHTML = `<p class="muted">${t("This element is only in the other revision.")}</p>`; return; }
  const lines = e.lines.filter((l) => l.guid === guid);
  const pe = e.per_element[guid] || {};
  const q = el.qty;
  const g = e.groups.find((x) => x.key === el.group);
  const wk = e.schedule?.elements?.[guid];
  $("#tab-element").innerHTML = `
    <div class="muted">${esc(el.kind || el.ifc_class)} · ${esc(el.level)}${el.model ? " · " + esc(el.model) : ""}</div>
    <h2 style="margin:4px 0 2px;font-size:16px">${esc(el.name)}</h2>
    <div class="total">${fmt(pe.total || 0)} <small>${e.currency}</small></div>
    <div class="settings" style="grid-template-columns:1fr">
      <label>${t("Priced as (applies to all {n} elements of this type)", { n: g ? g.count : "" })}<select id="elMap">${recipeOptions((S.project.settings.mappings || {})[el.group] || pe.recipe || "")}</select></label>
    </div>
    <div class="settings" style="grid-template-columns:110px 1fr">
      <label>${t("Adjust qty ×")}<input type="number" step="0.01" min="0" id="adjF" value="${(S.project.settings.adjustments || {})[el.group]?.factor ?? 1}"></label>
      <label>${t("Reason (required for an adjustment)")}<input type="text" id="adjR" value="${esc((S.project.settings.adjustments || {})[el.group]?.reason || "")}" placeholder="${t("e.g. slab thickened per structural drawing S-201")}"></label>
    </div>
    <h3>${t("Cost breakdown")}</h3>
    <table><thead><tr><th>${t("Work item")}</th><th class="n">${t("Qty")}</th><th class="n">${t("Rate")}</th><th class="n">${t("Amount")}</th></tr></thead><tbody>
    ${lines.map((l) => `<tr><td><span dir="auto">${esc(tx("work_item", l.work_item, l.description))}</span><br><span class="muted small" title="Quantity formula">= ${esc(l.formula)}${l.waste_pct ? ` + ${l.waste_pct}% ${t("waste")}` : ""}</span></td><td class="n">${fmt(uq(l.qty, l.unit)[0], 2)} ${uq(l.qty, l.unit)[1]}</td><td class="n">${fmt(ur(l.rate, l.unit), 2)}</td><td class="n">${fmt(l.amount)}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">${pe.source === "excluded" ? t("Excluded from the estimate.") : t("Not priced. Choose what it is above.")}</td></tr>`}
    </tbody></table>
    <h3>${t("Measured from the 3D shape")}</h3>
    <table>${[[t("Volume"), q.volume, "m³", "volume"], [t("Wall face (one side)"), q.side, "m²", "side"], [t("Plan area"), q.footprint, "m²", "footprint"], [t("Length"), q.length, "m", "length"], [t("Height"), q.height, "m", "height"], [t("Section size"), q.section, "m", "section"]]
      .map(([k, v, u, n]) => `<tr><td>${k} <span class="muted small">${n}</span></td><td class="n">${fmt(v, 3)} ${u}</td></tr>`).join("")}</table>
    ${el.authored?.volume ? `<p class="muted small">${t("Revit's own volume")}: <b>${fmt(el.authored.volume, 3)} m³</b> (${q.volume ? (q.volume / el.authored.volume - 1 > 0 ? "+" : "") + fmt((q.volume / el.authored.volume - 1) * 100, 1) + "% " + t("difference") : ""}).</p>` : ""}
    ${pe.overlap_m3 ? `<p class="callout" dir="auto">${t("{v} m³ deducted because it overlaps other elements that keep that volume.", { v: fmt(pe.overlap_m3, 3) })}</p>` : ""}
    ${pe.openings_kept_m2 ? `<p class="muted small">${t("{v} m² of small openings not deducted (measurement rule).", { v: fmt(pe.openings_kept_m2, 2) })}</p>` : ""}
    ${q.check === 2 ? `<p class="note">${t("Exported as a surface, not a solid: volume = face × material layer thickness.")}</p>` : q.check === 3 ? `<p class="note">${t("Shape could not be measured; Revit's own volume is used.")}</p>` : q.check === 1 ? `<p class="note">${t("Shape could not be measured; volume is a rough estimate. Check this element in Revit.")}</p>` : ""}
    ${wk ? `<p class="muted">${t("Built in weeks {a}–{b} of the 4D sequence.", { a: fmt(wk[0], 1), b: fmt(wk[1], 1) })}</p>` : ""}
    <h3>${t("Materials")}</h3><p>${el.materials.map((m) => `<span class="tag">${esc(m)}</span>`).join(" ") || `<span class="muted">${t("none in model")}</span>`}</p>
    ${(el.layers || []).length ? `<table>${el.layers.map((l) => `<tr><td>${esc(l.name)}</td><td class="n">${fmt(l.t * 1000)} mm</td></tr>`).join("")}</table>` : ""}
    ${el.classification?.length ? `<h3>${t("Classification")}</h3><p>${el.classification.map((c) => `<span class="tag">${esc(c)}</span>`).join(" ")}</p>` : ""}
    ${Object.keys(el.props || {}).length ? `<h3>${t("Properties")}</h3><table>${Object.entries(el.props).map(([k, v]) => `<tr><td>${esc(k.replaceAll("_", " "))}</td><td>${esc(v)}</td></tr>`).join("")}</table>` : ""}`;
  $("#elMap").addEventListener("change", (ev) => saveSettings({ mappings: { [el.group]: ev.target.value || null } }));
  const saveAdj = () => {
    const f = Number($("#adjF").value) || 1, r = $("#adjR").value.trim();
    if (f !== 1 && !r) { toast("Write a reason for the adjustment first."); $("#adjR").focus(); return; }
    saveSettings({ adjustments: { [el.group]: f === 1 ? null : { factor: f, reason: r } } });
  };
  $("#adjF").addEventListener("change", saveAdj);
  $("#adjR").addEventListener("change", () => { if (Number($("#adjF").value) !== 1) saveAdj(); });
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
  return `<svg style="direction:ltr" class="chart" viewBox="0 0 ${W} ${H}">${bars}
    <path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2"/>
    <text x="${P}" y="10">${fmt(max)} ${cur()}</text>
    <text x="${P}" y="${H - 4}">${t("Month")} 1</text><text x="${W - 60}" y="${H - 4}">${t("Month")} ${months.length}</text>
    ${nowX !== null ? `<line x1="${nowX}" x2="${nowX}" y1="12" y2="${H - 18}" stroke="var(--bad)" stroke-width="1.5"/>` : ""}</svg>`;
}

function renderTime() {
  const sc = S.est.schedule;
  if (!sc || !sc.activities.length) { $("#tab-time").innerHTML = `<p class="muted">${t("Nothing priced yet.")}</p>`; return; }
  const W = sc.weeks;
  const now = S.time;
  const months = S.project.settings.duration_months || 12;
  let cumNow = null;
  if (now !== null) { const m = Math.min(Math.floor(now / (52 / 12)), sc.months.length - 1); cumNow = sc.months[m]?.cumulative; }
  $("#tab-time").innerHTML = `
    <p class="muted">${t("An automatic construction sequence: foundations, then frame floor by floor, roof, envelope, services, finishes and fit-out. Each activity's length follows its cost. Use it to check cash flow early. It is not a replacement for a full programme.")}</p>
    <div class="settings" style="grid-template-columns:1fr 1fr"><label>${t("Construction time (months)")}<input type="number" min="1" max="120" id="durIn" value="${months}"></label>
      <label>${t("Cost spent by now")}<b style="color:var(--ink);font-size:15px">${now === null ? "–" : fmt(cumNow) + " " + cur()}</b></label></div>
    <div class="player"><button class="btn sm" id="playBtn">${t(S.playing ? "Pause" : "Play")}</button>
      <input type="range" id="timeSlider" min="0" max="${W}" step="0.25" value="${now ?? W}">
      <span class="small" style="width:76px;text-align:right">${now === null ? t("finished") : t("week") + " " + fmt(now, 1)}</span>
      <button class="btn sm" id="timeOff" ${now === null ? "disabled" : ""}>${t("Show all")}</button></div>
    <h3>${t("Cash flow (S-curve)")}</h3>${sCurve(sc.months, S.est.summary.total, now)}
    <h3>${t("Sequence")}</h3>
    <div class="gantt">${sc.activities.map((a) => `<div class="g-row"><span title="${esc(a.stage)} · ${esc(a.level)} · ${fmt(a.cost)} ${cur()}">${esc(t(a.stage.slice(2)))} · ${esc(a.level === "All levels" ? t(a.level) : a.level)}</span>
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
    body = `<div class="callout">${t("Upload a newer export of the same Revit model to see what changed and how the cost moved. Revit keeps element IDs stable between exports, so every added, removed or changed element is found.")}</div>`;
  } else if (c) {
    const d = c.total_after - c.total_before;
    body = `
      <div class="kpis">
        <div class="kpi"><span>${esc(c.a.label)} ${t("total")}</span><b>${fmt(c.total_before)}</b></div>
        <div class="kpi"><span>${esc(c.b.label)} ${t("total")}</span><b>${fmt(c.total_after)}</b></div>
        <div class="kpi"><span>${t("Difference")}</span><b class="${d > 0 ? "pos" : "neg"}">${d > 0 ? "+" : ""}${fmt(d)} ${c.currency}</b></div>
        <div class="kpi"><span>${t("Elements")}</span><b><span class="tag added">+${c.counts.added || 0}</span> <span class="tag removed">−${c.counts.removed || 0}</span> <span class="tag changed">~${c.counts.changed || 0}</span></b></div>
      </div>
      <h3>${t("By trade")}</h3>
      <table><thead><tr><th>${t("Trade")}</th><th class="n">${t("Before")}</th><th class="n">${t("After")}</th><th class="n">${t("Change")}</th></tr></thead><tbody>
      ${c.by_trade.filter((t) => Math.abs(t.delta) > 0.5).map((t) => `<tr><td>${esc(tx("trade", t.trade, t.trade))}</td><td class="n">${fmt(t.before)}</td><td class="n">${fmt(t.after)}</td><td class="n ${t.delta > 0 ? "pos" : "neg"}">${t.delta > 0 ? "+" : ""}${fmt(t.delta)}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">${t("No cost change.")}</td></tr>`}
      </tbody></table>
      <h3>${t("Changed elements")} (${c.rows.length})</h3>
      <table><tbody>${c.rows.slice(0, 300).map((r) => `<tr class="click" data-g="${r.guid}"><td>${esc(r.name)}<br><span class="tag ${r.status}">${t(r.status)}</span> <span class="muted small">${esc(r.why)}</span></td><td class="n ${r.delta > 0 ? "pos" : "neg"}">${r.delta > 0 ? "+" : ""}${fmt(r.delta)}</td></tr>`).join("")}</tbody></table>`;
  }
  $("#tab-compare").innerHTML = `
    <div class="toolbar"><label class="btn primary">${t("Upload new revision")}<input type="file" id="revFile" accept=".ifc,.ifczip,.zip" hidden></label>
      <span class="muted small">${t("of")} ${esc(S.version.discipline || t("this model"))}</span></div>
    <div class="callout small">${t("Separate Revit models for structure or MEP? Add each one here: the estimate adds them up (the latest revision of each), shows them together in 3D and counts elements drawn in two models once.")}
      <div class="toolbar" style="margin-top:6px"><select id="discSel">${["Structure", "MEP", "Electrical", "Plumbing", "Architecture", "Landscape"].map((d) => `<option value="${d}">${t(d)}</option>`).join("")}</select>
      <label class="btn">${t("Add a discipline model")}<input type="file" id="discFile" accept=".ifc,.ifczip,.zip" hidden></label></div>
      ${(S.models || []).length > 1 ? `<p class="small">${t("Combined now")}: ${S.models.map((m) => esc(m.label)).join(" + ")}</p>` : ""}</div>
    ${ready.length >= 2 ? `<div class="toolbar"><select id="cmpA">${opts(c?.a.id || prev?.id)}</select> → <select id="cmpB">${opts(c?.b.id || S.version.id)}</select><button class="btn" id="cmpRun">${t("Compare")}</button>${c ? `<button class="btn" id="cmpClear">${t("Clear")}</button>` : ""}</div>` : ""}
    <div class="toolbar"><label class="muted small">${t("Revision name")} <input type="text" id="verLabel" value="${esc(S.version.label)}" style="width:140px"></label></div>
    ${body}`;
  $("#revFile").addEventListener("change", (ev) => { const f = ev.target.files[0]; if (f) uploadFile(f, p.id, S.version.discipline || ""); });
  $("#discFile").addEventListener("change", (ev) => { const f = ev.target.files[0]; if (f) uploadFile(f, p.id, $("#discSel").value); });
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

// ---------- prices & rates ----------
// Three tabs: local resource prices (quick setup), work item rates (built up, with
// optional fixed rates), and region settings & sharing (rate packs, World Bank).
S.rd = { tab: "prices", region: null, prices: null, rates: null, dirty: false };

async function openRates(region, tabName) {
  S.rd.region = region || S.est?.region || $("#region").value || "GLOBAL";
  S.rd.tab = tabName || S.rd.tab || "prices";
  $("#rdRegion").innerHTML = Object.entries(S.lib.regions).map(([k, r]) => `<option value="${k}">${esc(r.name)} (${r.currency})</option>`).join("");
  $("#rdRegion").value = S.rd.region;
  $("#ratesDlg").hidden = false;
  await loadRd();
}
async function loadRd() {
  const r = S.rd.region;
  [S.rd.prices, S.rd.rates] = await Promise.all([api(`/api/prices/${r}`), api(`/api/rates/${r}`)]);
  S.rd.dirty = false;
  drawRd();
}
function drawRd() {
  $$("#rdTabs button").forEach((b) => b.classList.toggle("on", b.dataset.rt === S.rd.tab));
  $("#rateSearch").hidden = S.rd.tab === "region";
  $("#rateSave").hidden = S.rd.tab === "region";
  ({ prices: drawPrices, rates: drawRates, region: drawRegion })[S.rd.tab]();
}

function drawPrices() {
  const tb = S.rd.prices, q = ($("#rateSearch").value || "").toLowerCase(), cur = tb.currency;
  $("#rdHelp").innerHTML = t("Enter what things cost where you work, in {cur}. Every work-item rate is then built up from these prices (labour hours x wage + materials + plant). Start with the <b>key prices</b>; anything you leave empty is estimated from the region's exchange rate and price factors.", { cur }) +
    ` <b>${tb.rows.filter((x) => x.kind === "yours").length} / ${tb.rows.length}</b> ${t("prices entered")}.` +
    (tb.rows.some((x) => x.kind === "assumed") ? ` <span class="tag changed">${t("assumed")}</span> = indicative market level (late 2026), not a quotation. Prices change daily: type over them with today's prices.` : "");
  let group = null, html = `<table><thead><tr><th>${t("Resource")}</th><th>${t("Unit")}</th><th class="n">${t("Estimated")} (${cur})</th><th class="n">${t("Your price")} (${cur})</th><th>${t("Source / supplier")}</th><th>${t("Date")}</th></tr></thead><tbody>`;
  for (const r of tb.rows) {
    if (q && !(r.resource + " " + r.name + " " + tx("resource", r.resource, "")).toLowerCase().includes(q)) continue;
    const g = r.key ? t("Key prices (enter these first)") : { labour: t("Labour"), material: t("Materials"), plant: t("Plant / equipment") }[r.type];
    if (g !== group) { group = g; html += `<tr><td colspan="6"><b>${esc(g)}</b></td></tr>`; }
    const kindTag = r.kind === "yours" ? `<span class="tag added">${t("your price")}</span>` : r.kind === "assumed" ? `<span class="tag changed">${t("assumed")}</span>` : `<span class="tag">${t("estimated")}</span>`;
    html += `<tr data-res="${r.resource}" class="${r.kind === "yours" ? "local" : ""}"><td><span dir="auto">${esc(tx("resource", r.resource, r.name))}</span> ${kindTag}<br><span class="tag">${r.resource}</span></td><td>${esc(r.unit)}</td>
      <td class="n muted">${fmt(r.estimated, 2)}</td>
      <td class="n"><input type="number" step="any" min="0" data-f="price" value="${r.price ?? ""}" placeholder="${fmt(r.estimated, 2)}"></td>
      <td><input type="text" data-f="source" value="${esc(r.source)}" placeholder="${t("e.g. supplier quote")}"></td>
      <td><input type="text" data-f="date" value="${esc(r.date)}" placeholder="YYYY-MM-DD" style="width:100px"></td></tr>`;
  }
  $("#ratesBody").innerHTML = html + "</tbody></table>";
  $$("#ratesBody tr[data-res]").forEach((tr) => tr.addEventListener("input", () => {
    const r = S.rd.prices.rows.find((x) => x.resource === tr.dataset.res);
    const v = $("input[data-f=price]", tr).value;
    r.price = v === "" ? null : Number(v);
    const srcIn = $("input[data-f=source]", tr);
    if (/^ASSUMED/i.test(srcIn.value)) { srcIn.value = "user"; $("input[data-f=date]", tr).value = new Date().toISOString().slice(0, 10); }
    r.source = srcIn.value;
    r.kind = r.price === null ? "estimated" : /^ASSUMED/i.test(r.source) ? "assumed" : "yours";
    r.date = $("input[data-f=date]", tr).value;
    tr.classList.toggle("local", r.kind === "yours");
    S.rd.dirty = true;
  }));
}

function drawRates() {
  const tb = S.rd.rates, q = ($("#rateSearch").value || "").toLowerCase(), cur = tb.currency;
  $("#rdHelp").innerHTML = t("Each rate is built up from resources. Click a row to see how. Type a fixed rate only if you have a quote for the whole item; it replaces the build-up.");
  let trade = null, html = `<table><thead><tr><th>${t("Work item")}</th><th>${t("Unit")}</th><th class="n">${t("Built-up rate")} (${cur})</th><th class="n">${t("Your prices")}</th><th class="n">${t("Fixed rate")} (${cur})</th><th>${t("Source")}</th></tr></thead><tbody>`;
  for (const r of tb.rows) {
    if (q && !(r.work_item + " " + r.description + " " + r.trade + " " + tx("work_item", r.work_item, "")).toLowerCase().includes(q)) continue;
    if (r.trade !== trade) { trade = r.trade; html += `<tr><td colspan="6"><b>${esc(trade)}</b></td></tr>`; }
    const fixed = r.local ? r.local[0] + r.local[1] + r.local[2] : "";
    html += `<tr data-wi="${r.work_item}" class="click ${r.local ? "local" : ""}"><td><span dir="auto">${esc(tx("work_item", r.work_item, r.description))}</span><br><span class="tag">${r.work_item}</span></td><td>${r.unit}</td>
      <td class="n">${fmt(r.base[0] + r.base[1] + r.base[2], 2)}<br><span class="muted small">M ${fmt(r.base[0])} · L ${fmt(r.base[1])} · P ${fmt(r.base[2])}</span></td>
      <td class="n"><span class="tag ${r.local_share > 0.99 ? "added" : r.local_share > 0 ? "changed" : ""}">${Math.round(r.local_share * 100)}%</span></td>
      <td class="n"><input type="number" step="any" min="0" data-f="fixed" value="${fixed}" placeholder="—"></td>
      <td><input type="text" data-f="source" value="${esc(r.local ? r.source : "")}" placeholder="${t("quote / reference")}"></td></tr>
      <tr class="build" data-for="${r.work_item}" hidden><td colspan="6">${r.build.length ? `<table class="inner"><tr><th>${t("Resource")}</th><th class="n">${t("Qty per")} ${r.unit}</th><th class="n">${t("Price")}</th><th class="n">${t("Cost")}</th></tr>${r.build.map((b) => `<tr><td>${esc(b.name)} ${b.yours ? '<span class="tag added">' + t("your price") + "</span>" : b.kind === "assumed" ? '<span class="tag changed">' + t("assumed") + "</span>" : '<span class="tag">' + t("estimated") + "</span>"}</td><td class="n">${fmt(b.qty, 3)} ${esc(b.unit)}</td><td class="n">${fmt(b.price, 2)}</td><td class="n">${fmt(b.cost, 2)}</td></tr>`).join("")}</table>` : `<span class="muted">${t("No build-up; converted base rate.")}</span>`}</td></tr>`;
  }
  $("#ratesBody").innerHTML = html + "</tbody></table>";
  $$("#ratesBody tr[data-wi]").forEach((tr) => {
    tr.addEventListener("click", (ev) => { if (ev.target.tagName === "INPUT") return; const b = $(`#ratesBody tr[data-for="${tr.dataset.wi}"]`); b.hidden = !b.hidden; });
    tr.addEventListener("input", () => {
      const r = S.rd.rates.rows.find((x) => x.work_item === tr.dataset.wi);
      const v = $("input[data-f=fixed]", tr).value;
      r.local = v === "" ? null : [Number(v) || 0, 0, 0];
      r.source = $("input[data-f=source]", tr).value;
      tr.classList.toggle("local", !!r.local);
      S.rd.dirty = true;
    });
  });
}

async function drawRegion() {
  const code = S.rd.region, reg = S.lib.regions[code];
  $("#rdHelp").innerHTML = t("Set up any country. The tool is free: share your prices with colleagues as a rate pack file.");
  const countries = S.countries || (S.countries = await api("/api/countries"));
  $("#ratesBody").innerHTML = `
    <div class="two-col">
      <div>
        <h3>${t("This region")}: ${esc(reg.name)}</h3>
        <div class="settings">
          <label>${t("Name")}<input type="text" id="rgName" value="${esc(reg.name)}"></label>
          <label>${t("Currency")}<input type="text" id="rgCur" value="${esc(reg.currency)}" maxlength="3"></label>
          <label>${t("Exchange rate (currency per 1 USD)")}<input type="number" step="any" id="rgFx" value="${reg.fx_per_usd}"></label>
          <label>${esc(reg.tax_name)} %<input type="number" step="any" id="rgTax" value="${reg.tax_pct}"></label>
          <label>${t("Labour factor (US = 1)")}<input type="number" step="any" id="rgLab" value="${reg.labour_factor}"></label>
          <label>${t("Material factor (US = 1)")}<input type="number" step="any" id="rgMat" value="${reg.material_factor}"></label>
          <label>${t("Measurement standard")}<select id="rgStd">${Object.entries(S.lib.standards).map(([k, v]) => `<option value="${k}" ${k === reg.standard ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
          <label>${t("Preliminaries %")}<input type="number" step="any" id="rgPre" value="${reg.prelims_pct}"></label>
        </div>
        <p class="muted small">${esc(reg.notes || "")} ${reg.fx_source ? "· " + esc(reg.fx_source) : ""}</p>
        <div class="toolbar">
          <button class="btn primary" id="rgSave">${t("Save region")}</button>
          <button class="btn" id="rgWb" ${code === "GLOBAL" ? "disabled" : ""}>${t("Update from World Bank")}</button>
        </div>
        <h3>${t("Share")}</h3>
        <div class="toolbar">
          <a class="btn" href="/api/regions/${code}/pack.json">${t("Download rate pack")}</a>
          <label class="btn">${t("Import rate pack")}<input type="file" id="rgImport" accept=".json" hidden></label>
          <a class="btn" href="/api/rates/${code}/template.xlsx">${t("Rates to Excel")}</a>
          <label class="btn">${t("Rates from Excel / CSV")}<input type="file" id="rgRatesImport" accept=".xlsx,.csv" hidden></label>
        </div>
      </div>
      <div>
        <h3>${t("Add your country")}</h3>
        <div class="settings" style="grid-template-columns:1fr">
          <label>${t("Country")}<select id="rgNew"><option value="">${t("Choose…")}</option>${countries.map((c) => `<option value="${c.code}">${esc(c.name)} · ${c.currency}</option>`).join("")}</select></label>
          <label>${t("Region code (optional, e.g. NG_LAGOS for a city)")}<input type="text" id="rgNewCode" placeholder="NG_LAGOS"></label>
        </div>
        <button class="btn primary" id="rgCreate">${t("Create region")}</button>
        <p class="muted small">${t("After creating it: click Update from World Bank (needs internet) or type the exchange rate, then enter local prices in tab 1.")}</p>
      </div>
    </div>`;
  $("#rgSave").addEventListener("click", async () => {
    const values = { name: $("#rgName").value, currency: $("#rgCur").value.toUpperCase(), fx_per_usd: Number($("#rgFx").value),
      tax_pct: Number($("#rgTax").value), labour_factor: Number($("#rgLab").value), material_factor: Number($("#rgMat").value),
      plant_factor: Number($("#rgMat").value), standard: $("#rgStd").value, prelims_pct: Number($("#rgPre").value) };
    try { await api("/api/regions", { method: "POST", json: { code, values } }); await reloadLib(); toast(t("Region saved.")); await loadRd(); if (S.project) refresh(); } catch (e) { toast(e.message); }
  });
  $("#rgWb").addEventListener("click", async () => {
    toast(t("Asking the World Bank…"));
    try { await api(`/api/regions/${code}/worldbank`, { method: "POST" }); await reloadLib(); toast(t("Exchange rate and price level updated.")); S.rd.tab = "region"; await loadRd(); if (S.project) refresh(); } catch (e) { toast(e.message); }
  });
  $("#rgCreate").addEventListener("click", async () => {
    const c = $("#rgNew").value; if (!c) return toast(t("Choose a country."));
    const codeNew = ($("#rgNewCode").value.trim() || c).toUpperCase();
    try { await api("/api/regions", { method: "POST", json: { code: codeNew, values: {} } }); await reloadLib(); S.rd.region = codeNew; $("#rdRegion").innerHTML = Object.entries(S.lib.regions).map(([k, r]) => `<option value="${k}">${esc(r.name)} (${r.currency})</option>`).join(""); $("#rdRegion").value = codeNew; toast(t("Region created.")); await loadRd(); } catch (e) { toast(e.message); }
  });
  $("#rgImport").addEventListener("change", async (ev) => {
    const f = ev.target.files[0]; if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    try { const r = await api("/api/regions/import", { method: "POST", body: fd }); await reloadLib(); S.rd.region = r.region; toast(`${t("Imported")} ${r.prices} ${t("prices")}`); await openRates(r.region, "prices"); } catch (e) { toast(e.message); }
    ev.target.value = "";
  });
  $("#rgRatesImport").addEventListener("change", async (ev) => {
    const f = ev.target.files[0]; if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    try { const r = await api(`/api/rates/${code}/import`, { method: "POST", body: fd }); toast(`${t("Imported")} ${r.imported}`); await loadRd(); if (S.project) refresh(); } catch (e) { toast(e.message); }
    ev.target.value = "";
  });
}

async function reloadLib() {
  S.lib = await api("/api/library");
  const opts = Object.entries(S.lib.regions).map(([k, r]) => `<option value="${k}">${esc(r.name)} (${r.currency})</option>`).join("");
  const cur1 = $("#region").value, cur2 = $("#startRegion").value;
  $("#region").innerHTML = opts; $("#startRegion").innerHTML = opts;
  $("#region").value = S.project?.settings.region || cur1; $("#startRegion").value = cur2 || "GLOBAL";
}

$("#ratesBtn").addEventListener("click", () => openRates());
$("#reportBtn").addEventListener("click", () => openReport());
$("#rateSearch").addEventListener("input", () => drawRd());
$$("#rdTabs button").forEach((b) => b.addEventListener("click", () => { S.rd.tab = b.dataset.rt; drawRd(); }));
$("#rdRegion").addEventListener("change", async (e) => {
  if (S.rd.dirty && !confirm(t("Discard unsaved changes?"))) { e.target.value = S.rd.region; return; }
  S.rd.region = e.target.value; await loadRd();
});
$("#rateClose").addEventListener("click", () => {
  if (S.rd.dirty && !confirm(t("Close without saving your changes?"))) return;
  S.rd.dirty = false; $("#ratesDlg").hidden = true;
});
$("#rateSave").addEventListener("click", async () => {
  try {
    if (S.rd.tab === "prices") {
      const rows = S.rd.prices.rows.filter((r) => r.price !== null).map((r) => ({ resource: r.resource, price: r.price, source: r.source, date: r.date }));
      const res = await api(`/api/prices/${S.rd.region}`, { method: "PUT", json: rows });
      toast(`${t("Saved")} ${res.saved} ${t("prices")}`);
    } else {
      const rows = S.rd.rates.rows.filter((r) => r.local).map((r) => ({ work_item: r.work_item, material: r.local[0], labour: r.local[1], equipment: r.local[2], source: r.source || "quote" }));
      const res = await api(`/api/rates/${S.rd.region}`, { method: "PUT", json: rows });
      toast(`${t("Saved")} ${res.saved} ${t("fixed rates")}`);
    }
    await reloadLib();
    await loadRd();
    if (S.project) refresh();
  } catch (err) { toast(err.message); }
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
$("#showAll").addEventListener("click", () => { S.highlight = null; $$("tr.sel").forEach((x) => x.classList.remove("sel")); viewer.fit(); paint(); });
$("#fitBtn").addEventListener("click", () => viewer.fit(S.highlight ? [...S.highlight] : null));
$("#langSel").addEventListener("change", (e) => { setLang(e.target.value); if (S.est) refresh(); if (S.lib) loadProjects(); });
$("#unitSel").addEventListener("change", (e) => { S.units = e.target.value; localStorageSet("units", S.units); if (S.est) { renderBoq(); if (S.selected) renderElement(S.selected); } });
$("#helpBtn").addEventListener("click", () => { $("#helpDlg").hidden = false; });
$("#helpClose").addEventListener("click", () => { $("#helpDlg").hidden = true; });
$("#demoBtn").addEventListener("click", async () => {
  const r = await api(`/api/projects/sample/Ifc2x3_Duplex_Architecture.ifc?region=${$("#startRegion").value}`, { method: "POST" });
  await loadProjects();
  go(r.project_id, r.version_id);
});
$("#projImport").addEventListener("change", async (ev) => {
  const f = ev.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  try { const r = await api("/api/projects/import", { method: "POST", body: fd }); await loadProjects(); go(r.project_id); }
  catch (err) { toast(err.message); }
  ev.target.value = "";
});
$("#addCountry").addEventListener("click", () => openRates($("#startRegion").value || "GLOBAL", "region"));
$("#export").addEventListener("click", () => { location.href = `/api/projects/${S.project.id}/export.xlsx?version=${S.version.id}&lang=${getLang()}`; });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { S.highlight = null; S.selected = null; $$("tr.sel").forEach((x) => x.classList.remove("sel")); paint(); } });

init().catch((err) => toast(err.message));
