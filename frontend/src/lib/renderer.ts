/* Three.js 3D 渲染:场景、节点/边、布局、相机交互、动画 */

import { el, MENTION_COLOR } from "./util";
import { createForceLayout, type ForceEdge } from "./layout";
import * as THREE from "three";
import { CSS2DObject, CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";
import type { CameraState, GraphData, GraphEdge, GraphNode } from "../store";

// ---- Three.js state ----
let scene: THREE.Scene;
let camera: THREE.PerspectiveCamera;
let renderer: THREE.WebGLRenderer;
let labelRenderer: CSS2DRenderer;
let raycaster: THREE.Raycaster;
let mouse: THREE.Vector2;
let nodeGroups: Record<string, THREE.Group> = {};   // id -> THREE.Group
let nodeLabels: Record<string, CSS2DObject> = {};   // id -> CSS2DObject
let edgeLines: THREE.Line[] = [];                   // line with userData.edge
let flowParticles: { source: string; target: string; phase: number; speed: number }[] = [];
let flowPoints: THREE.Points | null = null;         // 沿 ECHO 边流动的光点(仅数据)
let flowTrails: THREE.Line[] = [];                  // 每条 ECHO 边的"流星"光尾(头亮尾暗的短光线)
let positions: Record<string, THREE.Vector3> = {};  // id -> THREE.Vector3
const cameraState: { radius: number; theta: number; phi: number } = {
  radius: 1500,
  theta: -Math.PI / 2 + 0.4,
  phi: Math.PI / 2 - 0.18,
};
const center = new THREE.Vector3(0, 0, 0); // 相机注视点(平移时移动它)
let lastInteraction = 0;
let dragging = false, dragButton = 0, lastX = 0, lastY = 0;
let hovering = false;          // 鼠标悬停在节点上时暂停自动旋转
const activePointers: Record<string, { x: number; y: number }> = {}; // 触摸多点支持
let pinchDist = 0;
let pinchMidX = 0; // 双指中点(用于二指平移)
let pinchMidY = 0;
let viewToken = 0;             // 防止异步布局的旧回调覆盖新视图
let hiddenLabelIds: Record<string, boolean> = {}; // 主图谱中默认隐藏标签的孤岛作品
let currentKind: string | null = null; // 当前视图类型(用于同视图增量同步)
let glowTexture: THREE.CanvasTexture | null = null;
let backgroundStars: THREE.Points | null = null;
let animFrameId: number | null = null;
let boundCleanups: (() => void)[] = []; // dispose 时统一移除的监听
let onCameraChange: ((cam: CameraState) => void) | null = null; // 由 React 注入
let lastCameraSync = 0;
let lastSyncedCam: CameraState | null = null;
let wheelTimer: number | null = null;
let resizeContainer: HTMLElement | null = null;

export function setOnCameraChange(fn: (cam: CameraState) => void) {
  onCameraChange = fn;
}

// 相机回传 React store(节流:持续交互期间最多每 200ms 一次)
function syncCameraToStore() {
  if (!onCameraChange) return;
  const cam = getCameraState();
  if (
    lastSyncedCam &&
    Math.abs(cam.theta - lastSyncedCam.theta) < 1e-6 &&
    Math.abs(cam.phi - lastSyncedCam.phi) < 1e-6 &&
    Math.abs(cam.radius - lastSyncedCam.radius) < 1e-4 &&
    Math.abs(cam.cx - lastSyncedCam.cx) < 1e-4 &&
    Math.abs(cam.cy - lastSyncedCam.cy) < 1e-4 &&
    Math.abs(cam.cz - lastSyncedCam.cz) < 1e-4
  ) {
    return;
  }
  const now = Date.now();
  if (now - lastCameraSync < 200) return;
  lastCameraSync = now;
  lastSyncedCam = cam;
  onCameraChange(cam);
}

export function getCameraState(): CameraState {
  return {
    theta: cameraState.theta,
    phi: cameraState.phi,
    radius: cameraState.radius,
    cx: center.x,
    cy: center.y,
    cz: center.z,
  };
}

function applyCameraState(cam: CameraState | null | undefined) {
  if (!cam) return;
  if (typeof cam.theta === "number") cameraState.theta = cam.theta;
  if (typeof cam.phi === "number") cameraState.phi = cam.phi;
  if (typeof cam.radius === "number") cameraState.radius = cam.radius;
  if (typeof cam.cx === "number") center.set(cam.cx, cam.cy || 0, cam.cz || 0);
  applyCamera();
}

// =============================== 初始化 ===============================

export function initThree(containerOrNull?: HTMLElement | null): void {
  const container = containerOrNull || el("graph");
  if (!container) return;
  resizeContainer = container;
  const w = container.clientWidth || 900;
  const h = container.clientHeight || 600;

  scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x05060f, 0.00030);

  camera = new THREE.PerspectiveCamera(55, w / h, 1, 12000);
  applyCamera();

  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(w, h);
  renderer.domElement.style.position = "absolute";
  renderer.domElement.style.top = "0";
  renderer.domElement.style.left = "0";
  renderer.domElement.style.zIndex = "1";
  renderer.domElement.style.cursor = "grab";
  container.appendChild(renderer.domElement);

  labelRenderer = new CSS2DRenderer();
  labelRenderer.setSize(w, h);
  labelRenderer.domElement.style.position = "absolute";
  labelRenderer.domElement.style.top = "0";
  labelRenderer.domElement.style.left = "0";
  labelRenderer.domElement.style.pointerEvents = "none";
  labelRenderer.domElement.style.zIndex = "2";
  container.appendChild(labelRenderer.domElement);

  addBackgroundStars();

  raycaster = new THREE.Raycaster();
  mouse = new THREE.Vector2();

  bindControls(container);
  window.addEventListener("resize", onResize);
  animate();
}

function applyCamera(): void {
  const r = cameraState.radius;
  const th = cameraState.theta;
  const ph = cameraState.phi;
  const offset = new THREE.Vector3(
    r * Math.sin(ph) * Math.cos(th),
    r * Math.cos(ph),
    r * Math.sin(ph) * Math.sin(th)
  );
  camera.position.copy(center).add(offset);
  camera.lookAt(center);
}

function addBackgroundStars(): void {
  const count = 1400;
  const posArr = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    const u = Math.random() * 2 - 1;
    const th = Math.random() * Math.PI * 2;
    const s = Math.sqrt(Math.max(0, 1 - u * u));
    const r = 2200 + Math.random() * 2300;
    posArr[i * 3] = r * s * Math.cos(th);
    posArr[i * 3 + 1] = r * u;
    posArr[i * 3 + 2] = r * s * Math.sin(th);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(posArr, 3));
  const mat = new THREE.PointsMaterial({
    color: 0xffffff,
    size: 1.7,
    transparent: true,
    opacity: 0.6,
    sizeAttenuation: true,
    fog: false,
  });
  const stars = new THREE.Points(geo, mat);
  stars.frustumCulled = false;
  backgroundStars = stars;
  scene.add(stars);
}

// =============================== 节点与边 ===============================

function makeGlowTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const ctx = c.getContext("2d")!;
  const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.25, "rgba(255,255,255,0.55)");
  g.addColorStop(0.6, "rgba(255,255,255,0.14)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
}

function createNodeGroup(n: GraphNode, pos: THREE.Vector3): void {
  const isAuthor = n.type === "author";
  const isExtra = !!n.__extra; // 作者名下额外作品:更小更暗,隐约环绕作者
  const color = isAuthor ? 0x9cc7ff : 0xffd166; // 作者星:蓝白 / 作品星:金色
  const r = isAuthor ? 6 : (isExtra ? 6.2 : 8.5);
  if (!glowTexture) glowTexture = makeGlowTexture();

  const core = new THREE.Mesh(
    new THREE.SphereGeometry(r, 14, 14),
    new THREE.MeshBasicMaterial({ color: color, transparent: true, opacity: isExtra ? 0.7 : 0.95, fog: false })
  );
  core.userData.node = n;
  core.userData.baseR = r;

  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: glowTexture,
      color: color,
      transparent: true,
      opacity: 0.55,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      fog: false,
    })
  );
  sprite.scale.set(r * 9, r * 9, 1);
  sprite.userData.phase = Math.random() * Math.PI * 2;
  sprite.userData.baseOpacity = isExtra ? 0.28 : 0.55;

  const group = new THREE.Group();
  group.add(core);
  group.add(sprite);
  // 不可见的放大命中球:仅用于拾取(悬停/点击),让瞄准更宽容
  const hit = new THREE.Mesh(
    new THREE.SphereGeometry(r * 3, 8, 8),
    new THREE.MeshBasicMaterial({ visible: false })
  );
  hit.userData.node = n;
  group.add(hit);
  group.userData.hit = hit;
  group.position.copy(pos);
  group.userData.core = core;
  group.userData.sprite = sprite;

  const div = document.createElement("div");
  div.className = "nodelabel";
  div.textContent = n.label;
  const label = new CSS2DObject(div);
  label.position.set(0, r + 12, 0);
  if (hiddenLabelIds[n.id]) {
    label.visible = false;           // 孤岛作品默认不显示文字(CSS2DRenderer 会强制改写 style.display,须用 visible)
    label.userData = { hiddenByDefault: true };
  }
  group.add(label);

  scene.add(group);
  nodeGroups[n.id] = group;
  nodeLabels[n.id] = label;
}

function createEdgeLine(e: GraphEdge): void {
  const isAuthored = e.type === "authored";
  if (!glowTexture) glowTexture = makeGlowTexture();
  let mat: THREE.LineBasicMaterial;
  if (isAuthored) {
    mat = new THREE.LineBasicMaterial({
      color: 0x7b88b8,
      transparent: true,
      opacity: 0.28,
      blending: THREE.NormalBlending,
      depthWrite: false,
      fog: true,
    });
  } else {
    // ECHO 提及线:轨道线(方向由流动的"流星"表达)
    mat = new THREE.LineBasicMaterial({
      color: MENTION_COLOR,
      transparent: true,
      opacity: 0.28,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      fog: true,
    });
  }
  const geo = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(),
    new THREE.Vector3(),
  ]);
  const line = new THREE.Line(geo, mat);
  line.userData.edge = e;
  scene.add(line);
  edgeLines.push(line);
  if (!isAuthored) {
    flowParticles.push({
      source: e.source,
      target: e.target,
      phase: Math.random(),
      speed: 0.00022 + Math.random() * 0.00012, // 每条边速度略不同
    });
    // 流星光尾:头亮尾暗的渐变短光线,随头部移动
    const trailGeo = new THREE.BufferGeometry();
    trailGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(6), 3));
    trailGeo.setAttribute("color", new THREE.BufferAttribute(new Float32Array(6), 3));
    const trailMat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.95,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      fog: true,
    });
    const trail = new THREE.Line(trailGeo, trailMat);
    trail.frustumCulled = false;
    scene.add(trail);
    flowTrails.push(trail);
  }
}

function initFlowParticles(): void {
  if (!flowParticles.length) { flowPoints = null; return; }
  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(flowParticles.length * 3);
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  const mat = new THREE.PointsMaterial({
    map: glowTexture,
    color: 0x9ff6ff,
    size: 14,
    transparent: true,
    opacity: 0.95,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    fog: false,
    sizeAttenuation: true,
  });
  flowPoints = new THREE.Points(geo, mat);
  flowPoints.frustumCulled = false;
  scene.add(flowPoints);
}

function updateEdgeLines(): void {
  edgeLines.forEach(function (line) {
    const e = line.userData.edge as GraphEdge;
    const pa = positions[e.source];
    const pb = positions[e.target];
    if (!pa || !pb) { line.visible = false; return; }
    line.visible = true;
    const attr = line.geometry.attributes.position as THREE.BufferAttribute;
    attr.setXYZ(0, pa.x, pa.y, pa.z);
    attr.setXYZ(1, pb.x, pb.y, pb.z);
    attr.needsUpdate = true;
  });
}

// =============================== 布局 ===============================

function layoutFor(kind: string, data: GraphData): Record<string, THREE.Vector3> {
  if (kind === "path") return pathLayout(data);
  return {};
}

function forceLayoutChunked(
  ids: string[],
  edges: ForceEdge[],
  callback: (pos: Record<string, THREE.Vector3>) => void
): void {
  // 优先用 Worker 异步计算;不可用或超时(8s)时回退到主线程分帧计算(共用 layout.ts 算法)
  if (typeof Worker !== "undefined") {
    let worker: Worker | null = null;
    let done = false;
    try {
      worker = new Worker(new URL("./layout.worker.ts", import.meta.url), { type: "module" });
      const timeout = window.setTimeout(() => {
        if (done) return;
        done = true;
        if (worker) worker.terminate();
        forceLayoutMainThread(ids, edges, callback); // worker 悬挂超时,回退主线程
      }, 8000);
      worker.onmessage = function (ev) {
        window.clearTimeout(timeout);
        if (done) return;
        done = true;
        if (worker) worker.terminate();
        const pos: Record<string, THREE.Vector3> = {};
        Object.keys(ev.data.positions || {}).forEach(function (id) {
          const p = ev.data.positions[id];
          pos[id] = new THREE.Vector3(p[0], p[1], p[2]);
        });
        callback(pos);
      };
      worker.onerror = function () {
        window.clearTimeout(timeout);
        if (done) return;
        done = true;
        if (worker) worker.terminate();
        forceLayoutMainThread(ids, edges, callback);
      };
      worker.postMessage({ ids: ids, edges: edges });
      return;
    } catch { /* Worker 不可用,走主线程回退 */ }
  }
  forceLayoutMainThread(ids, edges, callback);
}

function forceLayoutMainThread(
  ids: string[],
  edges: ForceEdge[],
  callback: (pos: Record<string, THREE.Vector3>) => void
): void {
  const layout = createForceLayout(ids, edges);

  function tick() {
    if (!layout.tick(14)) { // 每帧只算一小段,避免卡顿
      setTimeout(tick, 0);
      return;
    }
    const pos: Record<string, THREE.Vector3> = {};
    const plain = layout.result();
    Object.keys(plain).forEach(function (id) {
      pos[id] = new THREE.Vector3(plain[id][0], plain[id][1], plain[id][2]);
    });
    callback(pos);
  }

  tick();
}

function pathLayout(data: GraphData): Record<string, THREE.Vector3> {
  const positions: Record<string, THREE.Vector3> = {};
  const order = data.pathOrder || [];
  const n = order.length;
  order.forEach(function (id: string, i: number) {
    positions[id] = new THREE.Vector3(
      (i - (n - 1) / 2) * 300,
      Math.sin(i * 1.2) * 50,
      Math.cos(i * 1.2) * 50
    );
  });
  return positions;
}

// =============================== 视图管理 ===============================

function disposeGroup(g: THREE.Group): void {
  scene.remove(g);
  g.traverse(function (obj) {
    const mesh = obj as THREE.Mesh;
    if (mesh.geometry) mesh.geometry.dispose();
    if (mesh.material) {
      const mat = mesh.material as THREE.Material & { map?: THREE.Texture | null };
      if (mat.map) mat.map = null;
      mat.dispose();
    }
  });
}

function removeNodeGroup(id: string): void {
  // CSS2DRenderer 不会自动移除已离开场景的标签 DOM,需手动清理,否则旧书名残留
  const label = nodeLabels[id];
  if (label) {
    const elm = label.element;
    if (elm && elm.parentNode) elm.parentNode.removeChild(elm);
    delete nodeLabels[id];
  }
  const g = nodeGroups[id];
  if (g) {
    disposeGroup(g);
    delete nodeGroups[id];
  }
}

function clearEdges(): void {
  edgeLines.forEach(function (l) {
    scene.remove(l);
    l.geometry.dispose();
    (l.material as THREE.Material).dispose();
  });
  flowTrails.forEach(function (l) {
    scene.remove(l);
    l.geometry.dispose();
    (l.material as THREE.Material).dispose();
  });
  if (flowPoints) {
    scene.remove(flowPoints);
    flowPoints.geometry.dispose();
    if (flowPoints.material) {
      const mat = flowPoints.material as THREE.PointsMaterial;
      mat.map = null;
      mat.dispose();
    }
  }
  edgeLines = [];
  flowParticles = [];
  flowTrails = [];
  flowPoints = null;
}

function clearNodes(): void {
  Object.keys(nodeLabels).forEach(function (id) {
    const elm = nodeLabels[id].element;
    if (elm && elm.parentNode) elm.parentNode.removeChild(elm);
  });
  Object.keys(nodeGroups).forEach(function (id) {
    disposeGroup(nodeGroups[id]);
  });
  nodeGroups = {};
  nodeLabels = {};
}

function clearScene(): void {
  clearNodes();
  clearEdges();
  positions = {};
}

// 同视图增量更新:保留已有节点组与相机,只增删差异节点、重建边
function syncScene(data: GraphData): void {
  const keep: Record<string, boolean> = {};
  data.nodes.forEach(function (n) { keep[n.id] = true; });
  Object.keys(nodeGroups).forEach(function (id) {
    if (!keep[id]) removeNodeGroup(id);
  });
  data.nodes.forEach(function (n) {
    const p = positions[n.id] || new THREE.Vector3();
    if (nodeGroups[n.id]) {
      nodeGroups[n.id].position.copy(p);
      const label = nodeLabels[n.id];
      if (label) {
        if (hiddenLabelIds[n.id]) {
          label.visible = false;
          label.userData.hiddenByDefault = true;
        } else if (label.userData && label.userData.hiddenByDefault) {
          label.visible = true;
          delete label.userData.hiddenByDefault;
        }
      }
    } else {
      createNodeGroup(n, p);
    }
  });
  clearEdges();
  data.edges.forEach(createEdgeLine);
  initFlowParticles();
}

function buildScene(data: GraphData): void {
  data.nodes.forEach(function (n) {
    if (!positions[n.id]) {
      positions[n.id] = new THREE.Vector3(
        Math.random() * 120 - 60,
        Math.random() * 120 - 60,
        Math.random() * 120 - 60
      );
    }
    createNodeGroup(n, positions[n.id]);
  });
  data.edges.forEach(createEdgeLine);
  initFlowParticles();
}

// 受控入口:React 持有 viewData/currentView/相机,渲染器只负责按传入数据绘制。
// data.camera 存在时应用该相机(视图切换/深链恢复);不存在则保持当前相机(同视图刷新)。
export function update(kind: string, data: GraphData): void {
  const token = ++viewToken;
  const camera = data.camera as CameraState | undefined;
  hiddenLabelIds = kind === "main" ? isolatedWorkIds(data) : {};
  if (kind === "ripple") {
    // 额外作品默认不显示标签,悬停时再显示
    data.nodes.forEach(function (n) { if (n.__extra) hiddenLabelIds[n.id] = true; });
  }
  const finalize = () => {
    if (camera) applyCameraState(camera);
    lastInteraction = Date.now();
  };
  // 主图谱 / 作者视图 / 涟漪视图共用力导向布局,观感一致;
  // 涟漪视图额外把中心作品平移到原点,保留"中心-扩散"语义
  const forceKinds = kind === "main" || kind === "author" || kind === "ripple";
  const anchorRipple = (pos: Record<string, THREE.Vector3>): Record<string, THREE.Vector3> => {
    const c = kind === "ripple" ? pos[data.centerId as string] : undefined;
    if (c) {
      Object.keys(pos).forEach(function (id) { pos[id].sub(c); });
    }
    return pos;
  };
  if (currentKind === kind) {
    // 同视图刷新:增量同步,保持相机与已有节点(涟漪扩散 / 过滤开关切换)
    if (forceKinds) {
      forceLayoutChunked(data.nodes.map(function (n) { return n.id; }), data.edges, function (pos) {
        if (token !== viewToken) return;
        positions = anchorRipple(pos);
        syncScene(data);
        currentKind = kind;
        finalize();
      });
    } else {
      positions = layoutFor(kind, data);
      syncScene(data);
      currentKind = kind;
      finalize();
    }
    return;
  }
  clearScene();
  if (forceKinds) {
    // 主图谱与作者视图共用力导向布局(Worker 分帧),观感一致
    forceLayoutChunked(data.nodes.map(function (n) { return n.id; }), data.edges, function (pos) {
      if (token !== viewToken) return; // 期间已切换视图,丢弃本次布局结果
      positions = anchorRipple(pos);
      buildScene(data);
      currentKind = kind;
      finalize();
    });
    return;
  }
  positions = layoutFor(kind, data);
  buildScene(data);
  currentKind = kind;
  finalize();
}

function isolatedWorkIds(data: GraphData): Record<string, boolean> {
  const deg: Record<string, number> = {};
  data.edges.forEach(function (e) {
    if (e.type !== "echo") return;
    deg[e.source] = (deg[e.source] || 0) + 1;
    deg[e.target] = (deg[e.target] || 0) + 1;
  });
  const ids: Record<string, boolean> = {};
  data.nodes.forEach(function (n) {
    if (n.type === "work" && !deg[n.id]) ids[n.id] = true;
  });
  return ids;
}

// =============================== 交互 ===============================

function bindControls(container: HTMLElement): void {
  const dom = renderer.domElement;
  const ctl = new AbortController();
  boundCleanups.push(function () { ctl.abort(); });
  function bindEvent(
    target: HTMLElement,
    type: string,
    fn: (e: any) => void,
    extra?: { passive?: boolean }
  ): void {
    const o: AddEventListenerOptions = extra
      ? Object.assign({ signal: ctl.signal }, extra)
      : { signal: ctl.signal };
    target.addEventListener(type, fn, o);
  }

  function dist(p1: { x: number; y: number }, p2: { x: number; y: number }): number {
    return Math.sqrt((p1.x - p2.x) * (p1.x - p2.x) + (p1.y - p2.y) * (p1.y - p2.y));
  }

  bindEvent(dom, "pointerdown", function (e) {
    activePointers[e.pointerId] = { x: e.clientX, y: e.clientY };
    dragging = true;
    dragButton = e.button; // 0=左键(平移/选择),2=右键(旋转)
    lastX = e.clientX; lastY = e.clientY;
    lastInteraction = Date.now();
    if (dom.setPointerCapture) dom.setPointerCapture(e.pointerId);
    dom.style.cursor = "grabbing";
    if (Object.keys(activePointers).length === 2) {
      const ids = Object.keys(activePointers);
      pinchDist = dist(activePointers[ids[0]], activePointers[ids[1]]);
      pinchMidX = (activePointers[ids[0]].x + activePointers[ids[1]].x) / 2;
      pinchMidY = (activePointers[ids[0]].y + activePointers[ids[1]].y) / 2;
    }
  });
  bindEvent(dom, "pointermove", function (e) {
    if (dragging) {
      const ids = Object.keys(activePointers);
      if (ids.length >= 2 && activePointers[e.pointerId]) {
        // 双指手势:间距变化 → 缩放,中点位移 → 旋转(同时生效)
        activePointers[e.pointerId] = { x: e.clientX, y: e.clientY };
        if (ids.length === 2) {
          const a = activePointers[ids[0]];
          const b = activePointers[ids[1]];
          const d = dist(a, b);
          const mx = (a.x + b.x) / 2;
          const my = (a.y + b.y) / 2;
          if (pinchDist > 0 && d > 0) {
            cameraState.radius *= pinchDist / d; // 开合 → 缩放
            cameraState.radius = Math.max(50, Math.min(8000, cameraState.radius));
          }
          // 双指整体位移 → 旋转
          cameraState.theta -= (mx - pinchMidX) * 0.005;
          cameraState.phi -= (my - pinchMidY) * 0.005;
          cameraState.phi = Math.max(0.15, Math.min(Math.PI - 0.15, cameraState.phi));
          pinchDist = d;
          pinchMidX = mx;
          pinchMidY = my;
          lastInteraction = Date.now();
          applyCamera();
        }
        return;
      }
      const dx = e.clientX - lastX;
      const dy = e.clientY - lastY;
      lastX = e.clientX; lastY = e.clientY;
      if (dragButton === 2) {
        // 鼠标右键:旋转视角
        cameraState.theta -= dx * 0.005;
        cameraState.phi -= dy * 0.005;
        cameraState.phi = Math.max(0.15, Math.min(Math.PI - 0.15, cameraState.phi));
      } else {
        // 触摸单指 / 鼠标左键:平移视角
        panBy(dx, dy);
      }
      applyCamera();
    }
  });
  bindEvent(dom, "pointerup", function (e) {
    delete activePointers[e.pointerId];
    dragging = Object.keys(activePointers).length > 0;
    if (!dragging) dom.style.cursor = "grab";
    pinchDist = 0;
    pinchMidX = 0;
    pinchMidY = 0;
    const rest = Object.keys(activePointers);
    if (rest.length === 1) {
      // 双指抬起一根后,剩余单指继续旋转,同步基准点避免跳变
      lastX = activePointers[rest[0]].x;
      lastY = activePointers[rest[0]].y;
    }
    lastInteraction = Date.now();
    syncCameraToStore();
  });
  bindEvent(dom, "pointercancel", function (e) {
    delete activePointers[e.pointerId];
    dragging = Object.keys(activePointers).length > 0;
    dom.style.cursor = "grab";
    pinchDist = 0;
    pinchMidX = 0;
    pinchMidY = 0;
    const rest = Object.keys(activePointers);
    if (rest.length === 1) {
      lastX = activePointers[rest[0]].x;
      lastY = activePointers[rest[0]].y;
    }
    syncCameraToStore();
  });
  bindEvent(dom, "contextmenu", function (e) {
    e.preventDefault(); // 屏蔽右键菜单,右键用于旋转
  });
  bindEvent(container, "wheel", function (e) {
    e.preventDefault();
    cameraState.radius *= 1 + e.deltaY * 0.0011;
    cameraState.radius = Math.max(50, Math.min(8000, cameraState.radius));
    lastInteraction = Date.now();
    applyCamera();
    if (wheelTimer) window.clearTimeout(wheelTimer);
    wheelTimer = window.setTimeout(syncCameraToStore, 250);
  }, { passive: false });
}

function panBy(dx: number, dy: number): void {
  const forward = new THREE.Vector3().subVectors(center, camera.position).normalize();
  const right = new THREE.Vector3().crossVectors(forward, new THREE.Vector3(0, 1, 0)).normalize();
  const up = new THREE.Vector3().crossVectors(right, forward).normalize();
  const scale = cameraState.radius * 0.0016;
  center.add(right.clone().multiplyScalar(-dx * scale));
  center.add(up.clone().multiplyScalar(dy * scale));
}

// 射线拾取:由 React 事件委托调用,返回命中的节点 id
export function pickNode(clientX: number, clientY: number): string | null {
  const rect = renderer.domElement.getBoundingClientRect();
  mouse.x = ((clientX - rect.left) / rect.width) * 2 - 1;
  mouse.y = -((clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(mouse, camera);
  const meshes = Object.keys(nodeGroups).map(function (id) {
    return nodeGroups[id].userData.hit || nodeGroups[id].userData.core;
  });
  const hits = raycaster.intersectObjects(meshes, false);
  return hits.length ? (hits[0].object.userData.node as GraphNode).id : null;
}

// 悬停视觉状态(标签激活/孤岛标签临时显示/光标),由 React 事件委托调用
export function setHoveredNode(id: string | null): void {
  Object.keys(nodeLabels).forEach(function (nid) {
    const label = nodeLabels[nid];
    const elm = label.element;
    elm.classList.toggle("active", nid === id);
    if (label.userData && label.userData.hiddenByDefault) {
      label.visible = nid === id; // 悬停时临时显示孤岛标签
    }
  });
  renderer.domElement.style.cursor = id ? "pointer" : "grab";
  hovering = id != null;
}

function onResize() {
  const container = resizeContainer || el("graph");
  if (!container) return;
  const w = container.clientWidth || window.innerWidth;
  const h = container.clientHeight || window.innerHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
  labelRenderer.setSize(w, h);
}

// 组件卸载时释放 Three.js 资源(React StrictMode / 热更新下避免重复初始化与泄漏)
export function disposeThree() {
  if (animFrameId) {
    cancelAnimationFrame(animFrameId);
    animFrameId = null;
  }
  window.removeEventListener("resize", onResize);
  boundCleanups.forEach(function (fn) { try { fn(); } catch { /* ignore */ } });
  boundCleanups = [];
  if (wheelTimer) {
    window.clearTimeout(wheelTimer);
    wheelTimer = null;
  }
  clearScene();
  if (scene && backgroundStars) {
    scene.remove(backgroundStars);
    backgroundStars.geometry.dispose();
    (backgroundStars.material as THREE.Material).dispose();
    backgroundStars = null;
  }
  renderer.dispose();
  if (renderer.domElement && renderer.domElement.parentNode) {
    renderer.domElement.parentNode.removeChild(renderer.domElement);
  }
  if (labelRenderer.domElement && labelRenderer.domElement.parentNode) {
    labelRenderer.domElement.parentNode.removeChild(labelRenderer.domElement);
  }
  glowTexture = null;
  resizeContainer = null;
  hiddenLabelIds = {};
}

function animate() {
  animFrameId = requestAnimationFrame(animate);
  const now = Date.now();
    if (!hovering && now - lastInteraction > 1000) {
      cameraState.theta += 0.0016;
      applyCamera();
    }
  const t = now * 0.001;
  Object.keys(nodeGroups).forEach(function (id) {
    const g = nodeGroups[id];
    const sprite = g.userData.sprite;
    const phase = sprite.userData.phase;
    const base = sprite.userData.baseOpacity || 0.55;
    sprite.material.opacity = base * (0.76 + 0.45 * (0.5 + 0.5 * Math.sin(t * 2.1 + phase)));
    const core = g.userData.core;
    core.scale.setScalar(1 + 0.07 * Math.sin(t * 1.4 + phase));
  });
    // 流动"流星":头部光点 + 向后渐隐的光尾,沿 ECHO 边从 source 流向 target
    if (flowPoints && flowParticles.length) {
      const attr = flowPoints.geometry.attributes.position;
      flowParticles.forEach(function (p, i) {
        const pa = positions[p.source];
        const pb = positions[p.target];
        if (!pa || !pb) {
          attr.setXYZ(i, 0, -10000, 0);
          return;
        }
        const progress = (now * p.speed + p.phase) % 1;
        const hx = pa.x + (pb.x - pa.x) * progress;
        const hy = pa.y + (pb.y - pa.y) * progress;
        const hz = pa.z + (pb.z - pa.z) * progress;
        attr.setXYZ(i, hx, hy, hz);
        const trail = flowTrails[i];
        if (trail) {
          const tailT = Math.max(0, progress - 0.14); // 光尾长度约为边的 14%
          const tPos = trail.geometry.attributes.position;
          tPos.setXYZ(0, hx, hy, hz);
          tPos.setXYZ(
            1,
            pa.x + (pb.x - pa.x) * tailT,
            pa.y + (pb.y - pa.y) * tailT,
            pa.z + (pb.z - pa.z) * tailT
          );
          tPos.needsUpdate = true;
          const tCol = trail.geometry.attributes.color;
          tCol.setXYZ(0, 0.82, 0.99, 1.0);   // 头部亮青白
          tCol.setXYZ(1, 0.02, 0.04, 0.10);  // 尾部渐隐至背景色
          tCol.needsUpdate = true;
        }
      });
      attr.needsUpdate = true;
    }
    updateEdgeLines();
    renderer.render(scene, camera);
  labelRenderer.render(scene, camera);
}
