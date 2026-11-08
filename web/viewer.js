// 3D viewer: loads the packed geometry of a model version and colours elements.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export class Viewer {
  constructor(host, { onPick } = {}) {
    this.host = host;
    this.onPick = onPick;
    this.meshes = new Map();       // guid -> mesh
    this.ghosts = new Map();       // guid -> mesh (from another version, e.g. removed elements)
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    host.appendChild(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.5));
    const sun = new THREE.DirectionalLight(0xffffff, 1.5);
    sun.position.set(30, 60, 20);
    this.scene.add(sun);
    this.group = new THREE.Group();
    this.scene.add(this.group);
    this.ghostGroup = new THREE.Group();
    this.scene.add(this.ghostGroup);
    this.edges = false;
    this._theme();
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => this._theme());
    new ResizeObserver(() => this._resize()).observe(host);
    this._resize();
    this._pickEvents();
    // Draw only when something changed: large models stay responsive and laptops stay cool.
    this.dirty = true;
    this.controls.addEventListener("change", () => (this.dirty = true));
    const loop = () => {
      this.controls.update();
      if (this.dirty) { this.dirty = false; this.renderer.render(this.scene, this.camera); }
      requestAnimationFrame(loop);
    };
    loop();
  }

  _theme() {
    const dark = matchMedia("(prefers-color-scheme: dark)").matches;
    this.scene.background = new THREE.Color(dark ? 0x0f131a : 0xeef1f5);
    this.dirty = true;
  }

  _resize() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    this.renderer.setSize(w, h);
    this.camera.aspect = w / Math.max(h, 1);
    this.camera.updateProjectionMatrix();
    this.dirty = true;
  }

  redraw() { this.dirty = true; }

  _pickEvents() {
    const ray = new THREE.Raycaster();
    let down = null;
    const el = this.renderer.domElement;
    el.addEventListener("pointerdown", (e) => (down = [e.clientX, e.clientY]));
    el.addEventListener("pointerup", (e) => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
      const r = el.getBoundingClientRect();
      ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), this.camera);
      const objs = [...this.group.children, ...this.ghostGroup.children].filter((o) => o.visible);
      const hit = ray.intersectObjects(objs)[0];
      this.onPick && this.onPick(hit ? hit.object.userData.guid : null);
    });
  }

  static async fetchGeometry(vid) {
    const [index, buf] = await Promise.all([
      fetch(`/api/versions/${vid}/geometry.json`).then((r) => r.json()),
      fetch(`/api/versions/${vid}/geometry.bin`).then((r) => r.arrayBuffer()),
    ]);
    const pos = new Float32Array(buf, 0, index.vertex_floats);
    const idx = new Uint32Array(buf, index.vertex_floats * 4, index.index_count);
    return { index, pos, idx };
  }

  _mesh(guid, g, item, material) {
    const [vo, vc, io, ic] = item;
    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position", new THREE.BufferAttribute(g.pos.subarray(vo * 3, (vo + vc) * 3), 3));
    geom.setIndex(new THREE.BufferAttribute(g.idx.slice(io, io + ic), 1));
    geom.computeVertexNormals();
    const mesh = new THREE.Mesh(geom, material);
    mesh.userData.guid = guid;
    return mesh;
  }

  load(g) {
    this.clear();
    this.add(g, false);
    // New model: start from a standard 3/4 view from above.
    this.camera.position.set(1, 0.8, 1);
    this.controls.target.set(0, 0, 0);
    this.fit();
  }

  // Add another model's geometry (a second discipline model) to the scene.
  add(g, fit = true) {
    for (const [guid, item] of Object.entries(g.index.items)) {
      if (this.meshes.has(guid)) continue;
      const mat = new THREE.MeshStandardMaterial({ color: 0xcccccc, roughness: 0.85, side: THREE.DoubleSide,
                                                   polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
      const mesh = this._mesh(guid, g, item, mat);
      this.group.add(mesh);
      this.meshes.set(guid, mesh);
    }
    if (fit) this.fit();
    this.dirty = true;
  }

  addGhosts(g, guids, color = 0xdc2626) {
    this.clearGhosts();
    for (const guid of guids) {
      const item = g.index.items[guid];
      if (!item) continue;
      const mat = new THREE.MeshStandardMaterial({ color, transparent: true, opacity: 0.55, side: THREE.DoubleSide });
      const mesh = this._mesh(guid, g, item, mat);
      this.ghostGroup.add(mesh);
      this.ghosts.set(guid, mesh);
    }
    this.dirty = true;
  }

  clearGhosts() {
    for (const m of this.ghosts.values()) { m.geometry.dispose(); m.material.dispose(); }
    this.ghostGroup.clear();
    this.ghosts.clear();
  }

  clear() {
    this.clearGhosts();
    for (const m of this.meshes.values()) { m.geometry.dispose(); m.material.dispose(); }
    this.group.clear();
    this.meshes.clear();
    this.dirty = true;
  }

  fit(guids) {
    const box = new THREE.Box3();
    if (guids && guids.length) guids.forEach((g) => { const m = this.meshes.get(g) || this.ghosts.get(g); if (m) box.expandByObject(m); });
    else box.setFromObject(this.group);
    if (box.isEmpty()) return;
    const c = box.getCenter(new THREE.Vector3());
    const r = Math.max(box.getSize(new THREE.Vector3()).length(), 2);
    this.controls.target.copy(c);
    const dir = this.camera.position.clone().sub(c).normalize();
    if (!isFinite(dir.x) || dir.length() < 0.5) dir.set(0.7, 0.55, 0.7).normalize();
    this.camera.position.copy(c.clone().add(dir.multiplyScalar(r * 1.1)));
    this.camera.near = r / 2000; this.camera.far = r * 40;
    this.camera.updateProjectionMatrix();
    this.dirty = true;
  }

  // style: (guid) -> {color: THREE.Color|hex|css, visible: bool, opacity: number, emissive: hex}
  paint(style) {
    for (const [guid, m] of this.meshes) {
      const s = style(guid) || {};
      m.visible = s.visible !== false;
      if (s.color !== undefined) m.material.color.set(s.color);
      const op = s.opacity ?? 1;
      m.material.transparent = op < 1;
      m.material.opacity = op;
      m.material.depthWrite = op >= 1;
      m.material.emissive.set(s.emissive ?? 0x000000);
    }
    this.dirty = true;
  }

  screenshot() { this.renderer.render(this.scene, this.camera); return this.renderer.domElement.toDataURL("image/png"); }
}
