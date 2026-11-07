import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const $ = (s) => document.querySelector(s);
const state = { model: null, geo: null, est: null, region: "SA", mode: "cost", selected: null, meshes: {} };

// ---------- 3D viewer ----------
const host = $("#canvas");
const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(window.devicePixelRatio);
host.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.6));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(30, 60, 20);
scene.add(sun);
const group = new THREE.Group();
scene.add(group);

function bg() {
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  scene.background = new THREE.Color(dark ? 0x0f131a : 0xeef1f5);
}
bg();
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", bg);

function resize() {
  const { clientWidth: w, clientHeight: h } = host;
  renderer.setSize(w, h);
  camera.aspect = w / Math.max(h, 1);
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(host);
(function loop() { controls.update(); renderer.render(scene, camera); requestAnimationFrame(loop); })();

function buildScene(geo) {
  group.clear();
  state.meshes = {};
  for (const [guid, m] of Object.entries(geo.meshes)) {
    if (!m.f.length) continue;
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(m.v, 3));
    g.setIndex(m.f);
    g.computeVertexNormals();
    const mat = new THREE.MeshStandardMaterial({ color: 0xcccccc, roughness: 0.8, side: THREE.DoubleSide,
                                                 polygonOffset: true, polygonOffsetFactor: 1 });
    const mesh = new THREE.Mesh(g, mat);
    mesh.userData.guid = guid;
    group.add(mesh);
    state.meshes[guid] = mesh;
  }
  const box = new THREE.Box3().setFromObject(group);
  const c = box.getCenter(new THREE.Vector3());
  const r = box.getSize(new THREE.Vector3()).length() || 10;
  controls.target.copy(c);
  camera.position.set(c.x + r * 0.7, c.y + r * 0.55, c.z + r * 0.7);
  camera.near = r / 1000; camera.far = r * 20; camera.updateProjectionMatrix();
}

// click to select
const ray = new THREE.Raycaster();
let down = null;
renderer.domElement.addEventListener("pointerdown", (e) => (down = [e.clientX, e.clientY]));
renderer.domElement.addEventListener("pointerup", (e) => {
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
  const r = renderer.domElement.getBoundingClientRect();
  ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
  const hit = ray.intersectObjects(group.children)[0];
  select(hit ? hit.object.userData.guid : null, true);
});

// ---------- colouring ----------
const TRADE_COLORS = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2", "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac", "#86bcb6", "#d4a6c8"];
function ramp(t) {
  const stops = ["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c"].map((h) => new THREE.Color(h));
  const x = Math.min(Math.max(t, 0), 1) * (stops.length - 1), i = Math.min(Math.floor(x), stops.length - 2);
  return stops[i].clone().lerp(stops[i + 1], x - i);
}
const mainTrade = {};
function recolor() {
  const est = state.est;
  if (!est) return;
  const totals = Object.values(est.per_element).map((p) => p.total).filter((v) => v > 0).sort((a, b) => a - b);
  const p95 = totals[Math.floor(totals.length * 0.95)] || 1;
  const trades = Object.keys(est.by_trade);
  const flagged = new Set(est.checks.geometry_flagged), unc = new Set(est.checks.unclassified);
  for (const l of est.lines) {
    const cur = mainTrade[l.guid];
    if (!cur || l.amount > cur.amount) mainTrade[l.guid] = { trade: l.trade, amount: l.amount };
  }
  let legend = "";
  if (state.mode === "cost") legend = `<div class="ramp"></div><div class="ramp-l"><span>low</span><span>${fmt(p95)}+ ${est.currency}</span></div>`;
  if (state.mode === "trade") legend = trades.map((t, i) => `<div class="key"><span class="sw" style="background:${TRADE_COLORS[i % 12]}"></span>${t}</div>`).join("");
  if (state.mode === "check") legend = `<div class="key"><span class="sw" style="background:#15803d"></span>OK</div><div class="key"><span class="sw" style="background:#f59e0b"></span>Geometry needs review</div><div class="key"><span class="sw" style="background:#dc2626"></span>Not classified (no price)</div>`;
  $("#legendBody").innerHTML = legend;
  for (const [guid, mesh] of Object.entries(state.meshes)) {
    let col;
    const pe = est.per_element[guid];
    if (state.mode === "cost") col = pe && pe.total > 0 ? ramp(Math.sqrt(pe.total / p95)) : new THREE.Color(0x999999);
    else if (state.mode === "trade") { const t = mainTrade[guid]; col = new THREE.Color(t ? TRADE_COLORS[trades.indexOf(t.trade) % 12] : "#999999"); }
    else col = new THREE.Color(unc.has(guid) ? "#dc2626" : flagged.has(guid) ? "#f59e0b" : "#15803d");
    mesh.material.color.copy(col);
    mesh.material.emissive.set(guid === state.selected ? 0x3355ff : 0x000000);
    mesh.material.transparent = !!state.highlight && !state.highlight.has(guid);
    mesh.material.opacity = mesh.material.transparent ? 0.12 : 1;
  }
}

// ---------- panels ----------
const fmt = (n, d = 0) => Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function bars(obj, cur) {
  const max = Math.max(...Object.values(obj), 1);
  return Object.entries(obj).map(([k, v]) => `<div class="bar"><span title="${esc(k)}">${esc(k)}</span><div class="track"><div class="fill" style="width:${(v / max) * 100}%"></div></div><span class="v">${fmt(v)}</span></div>`).join("");
}

function renderSummary() {
  const e = state.est, s = e.summary, c = e.checks;
  const sample = e.boq.some((b) => String(b.rate_source).startsWith("SAMPLE"));
  $("#tab-summary").innerHTML = `
    <div class="muted">${esc(e.project)} · ${esc(e.region_name)}</div>
    <div class="total">${fmt(s.total)} <small>${e.currency}</small></div>
    <div class="muted">Total incl. ${esc(s.tax_name)} ${s.tax_pct}%</div>
    <div class="kpis">
      <div class="kpi"><span>Direct cost</span><b>${fmt(s.direct)}</b></div>
      <div class="kpi"><span>Overhead ${s.overhead_pct}% + profit ${s.profit_pct}%</span><b>${fmt(s.overhead + s.profit)}</b></div>
      <div class="kpi"><span>Elements priced</span><b>${c.priced} / ${c.elements}</b></div>
      <div class="kpi"><span>Need review</span><b>${c.unclassified.length + c.geometry_flagged.length}</b></div>
    </div>
    <h3>By trade (${e.currency})</h3>${bars(e.by_trade)}
    <h3>By level (${e.currency})</h3>${bars(e.by_level)}
    ${sample ? `<p class="note">Rates marked SAMPLE are placeholders. Replace them in data/rates/ with your own prices before using this estimate.</p>` : ""}`;
}

function renderBoq() {
  const e = state.est;
  $("#tab-boq").innerHTML = `<p class="muted">Click a row to highlight its elements in 3D.</p>
  <table><thead><tr><th>Item</th><th class="n">Qty</th><th class="n">Rate</th><th class="n">Amount</th></tr></thead><tbody>
  ${e.boq.map((b) => `<tr class="click" data-wi="${b.work_item}"><td>${esc(b.description)}<br><span class="tag">${b.work_item}</span> <span class="tag">${esc(b.trade)}</span></td>
    <td class="n">${fmt(b.qty, 2)} ${b.unit}</td><td class="n">${fmt(b.rate, 2)}</td><td class="n">${fmt(b.amount)}</td></tr>`).join("")}
  </tbody><tfoot><tr><th>Direct cost</th><th></th><th></th><th class="n">${fmt(e.summary.direct)}</th></tr></tfoot></table>`;
  $("#tab-boq").querySelectorAll("tr[data-wi]").forEach((tr) => tr.addEventListener("click", () => {
    const on = tr.classList.contains("sel");
    $("#tab-boq").querySelectorAll("tr.sel").forEach((x) => x.classList.remove("sel"));
    if (on) state.highlight = null;
    else { tr.classList.add("sel"); state.highlight = new Set(e.lines.filter((l) => l.work_item === tr.dataset.wi).map((l) => l.guid)); }
    recolor();
  }));
}

function renderChecks() {
  const e = state.est, c = e.checks, els = state.geo.elements;
  const list = (ids) => ids.slice(0, 200).map((g) => `<tr class="click" data-g="${g}"><td>${esc(els[g]?.name)}<br><span class="tag">${els[g]?.ifc_class}</span></td></tr>`).join("");
  $("#tab-checks").innerHTML = `
    <p>${c.unclassified.length === 0 ? '<b class="ok">Every element was classified.</b>' : `<b>${c.unclassified.length}</b> elements have no matching rule, so they have no price. Add a rule in <code>data/rules.csv</code>.`}</p>
    <table>${list(c.unclassified)}</table>
    <h3>Geometry needs review (${c.geometry_flagged.length})</h3>
    <p class="muted">Their 3D shape is not a closed solid, so the volume is estimated from the bounding box. Check these in Revit.</p>
    <table>${list(c.geometry_flagged)}</table>`;
  $("#tab-checks").querySelectorAll("tr[data-g]").forEach((tr) => tr.addEventListener("click", () => select(tr.dataset.g, true)));
}

function select(guid, show) {
  state.selected = guid;
  recolor();
  if (!guid) return;
  const el = state.geo.elements[guid], e = state.est;
  const lines = e.lines.filter((l) => l.guid === guid);
  const pe = e.per_element[guid];
  const q = el.qty;
  $("#tab-element").innerHTML = `
    <div class="muted">${el.ifc_class} · ${esc(el.level)}</div>
    <h2 style="margin:4px 0 2px;font-size:16px">${esc(el.name)}</h2>
    <div class="total">${fmt(pe?.total || 0)} <small>${e.currency}</small></div>
    <div class="muted">Recipe: ${pe?.recipe ? `<span class="tag">${pe.recipe}</span>` : '<b style="color:var(--warn)">none (not priced)</b>'}</div>
    <h3>Cost breakdown</h3>
    <table><thead><tr><th>Work item</th><th class="n">Qty</th><th class="n">Amount</th></tr></thead><tbody>
    ${lines.map((l) => `<tr><td>${esc(l.description)}</td><td class="n">${fmt(l.qty, 2)} ${l.unit}</td><td class="n">${fmt(l.amount)}</td></tr>`).join("") || '<tr><td colspan="3" class="muted">No cost lines</td></tr>'}
    </tbody></table>
    <h3>Measured quantities</h3>
    <table>${[["Volume", q.volume, "m³"], ["Wall face (side)", q.side, "m²"], ["Plan area", q.footprint, "m²"], ["Length", q.length, "m"], ["Height", q.height, "m"]]
      .map(([k, v, u]) => `<tr><td>${k}</td><td class="n">${fmt(v, 3)} ${u}</td></tr>`).join("")}</table>
    ${q.check ? '<p class="note">Geometry is not a closed solid; volume is estimated.</p>' : ""}
    <h3>Materials</h3><p>${el.materials.map((m) => `<span class="tag">${esc(m)}</span>`).join(" ") || '<span class="muted">none in model</span>'}</p>`;
  if (show) tab("element");
}

function tab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.id === "tab-" + name));
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => tab(b.dataset.tab)));
document.querySelectorAll("#colorMode button").forEach((b) => b.addEventListener("click", () => {
  state.mode = b.dataset.mode;
  document.querySelectorAll("#colorMode button").forEach((x) => x.classList.toggle("on", x === b));
  recolor();
}));

// ---------- data loading ----------
async function api(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
function busy(on, text = "Reading model…") { $("#busy").hidden = !on; $("#busy span").textContent = text; }

async function open(promise) {
  busy(true);
  try {
    state.model = await promise;
    state.geo = await api(`/api/models/${state.model.id}/geometry`);
    $("#empty").hidden = true;
    buildScene(state.geo);
    await price();
    $("#export").disabled = false;
  } catch (err) { alert(err.message); }
  busy(false);
}
async function price() {
  if (!state.model) return;
  state.est = await api(`/api/models/${state.model.id}/estimate?region=${state.region}`);
  for (const k in mainTrade) delete mainTrade[k];
  state.highlight = null;
  renderSummary(); renderBoq(); renderChecks(); recolor();
  if (state.selected) select(state.selected, false);
}

$("#file").addEventListener("change", (e) => {
  const f = e.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  open(api("/api/models", { method: "POST", body: fd }));
  e.target.value = "";
});
$("#sample").addEventListener("change", (e) => { if (e.target.value) open(api(`/api/models/sample/${encodeURIComponent(e.target.value)}`, { method: "POST" })); e.target.value = ""; });
$("#region").addEventListener("change", (e) => { state.region = e.target.value; price(); });
$("#export").addEventListener("click", () => { location.href = `/api/models/${state.model.id}/export.xlsx?region=${state.region}`; });

(async () => {
  const [regions, samples] = await Promise.all([api("/api/regions"), api("/api/samples")]);
  $("#region").innerHTML = Object.entries(regions).map(([k, r]) => `<option value="${k}">${r.name} (${r.currency})</option>`).join("");
  $("#region").value = state.region;
  $("#sample").innerHTML += samples.map((s) => `<option>${esc(s)}</option>`).join("");
})();
