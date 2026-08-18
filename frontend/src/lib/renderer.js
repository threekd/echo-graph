/* Three.js 3D 渲染:场景、节点/边、布局、相机交互、动画 */

import { el, MENTION_COLOR } from "./util.js";

// ---- Three.js state ----
var scene, camera, renderer, labelRenderer, raycaster, mouse;
var nodeGroups = {};   // id -> THREE.Group
var nodeLabels = {};   // id -> CSS2DObject
var edgeLines = [];    // line with userData.edge
var flowParticles = []; // 沿 ECHO 边流动的光点(仅数据)
var flowPoints = null;  // THREE.Points 粒子系统
var flowTrails = [];   // 每条 ECHO 边的"流星"光尾(头亮尾暗的短光线)
var positions = {};    // id -> THREE.Vector3
var cameraState = { radius: 1500, theta: -Math.PI / 2 + 0.4, phi: Math.PI / 2 - 0.18 };
var center = new THREE.Vector3(0, 0, 0); // 相机注视点(平移时移动它)
var lastInteraction = 0;
var dragging = false, dragButton = 0, dragMoved = false, lastX = 0, lastY = 0;
var hovering = false;          // 鼠标悬停在节点上时暂停自动旋转
var lastHoveredNodeId = null;
var activePointers = {};       // 触摸多点支持
var pinchDist = 0;
var viewToken = 0;             // 防止异步布局的旧回调覆盖新视图
var hiddenLabelIds = {};       // 主图谱中默认隐藏标签的孤岛作品
var glowTexture = null;
var backgroundStars = null;
var currentView = "main";      // 当前视图:main / ripple / path / author
var fullData = { nodes: [], edges: [] }; // 全量数据(加载完成后由 App 注入)
var animFrameId = null;
var boundCleanups = [];        // dispose 时统一移除的监听
var onNodeClick = null; // 由 main.js 注入(避免循环依赖)
var onNodeHover = null; // 由 main.js 注入(悬停显示详情)
var onViewChange = null; // 由 React 注入(视图状态变化回调)
var resizeContainer = null;

export function setOnViewChange(fn) {
  onViewChange = fn;
}

export function setOnNodeClick(fn) {
  onNodeClick = fn;
}

export function setOnNodeHover(fn) {
  onNodeHover = fn;
}

// App 在数据加载完成后注入全量数据,供"显示作家节点"恢复等场景使用
export function setFullData(data) {
  fullData = data || { nodes: [], edges: [] };
}

export function sceneNodeCount() {
  return Object.keys(nodeGroups).length;
}

export function getCameraState() {
  return {
    theta: cameraState.theta,
    phi: cameraState.phi,
    radius: cameraState.radius,
    cx: center.x,
    cy: center.y,
    cz: center.z,
  };
}

export function applyCameraState(cam) {
  if (!cam) return;
  if (typeof cam.theta === "number") cameraState.theta = cam.theta;
  if (typeof cam.phi === "number") cameraState.phi = cam.phi;
  if (typeof cam.radius === "number") cameraState.radius = cam.radius;
  if (typeof cam.cx === "number") center.set(cam.cx, cam.cy || 0, cam.cz || 0);
  applyCamera();
}

// =============================== 初始化 ===============================

export function initThree(containerOrNull) {
  var container = containerOrNull || el("graph");
  resizeContainer = container;
  var w = container.clientWidth || 900;
  var h = container.clientHeight || 600;

  scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x05060f, 0.00030);

  camera = new THREE.PerspectiveCamera(55, w / h, 1, 12000);
  applyCamera();

  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(w, h);
  renderer.domElement.style.position = "absolute";
  renderer.domElement.style.top = "0";
  renderer.domElement.style.left = "0";
  renderer.domElement.style.zIndex = "1";
  renderer.domElement.style.cursor = "grab";
  container.appendChild(renderer.domElement);

  labelRenderer = new THREE.CSS2DRenderer();
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

function applyCamera() {
  var r = cameraState.radius;
  var th = cameraState.theta;
  var ph = cameraState.phi;
  var offset = new THREE.Vector3(
    r * Math.sin(ph) * Math.cos(th),
    r * Math.cos(ph),
    r * Math.sin(ph) * Math.sin(th)
  );
  camera.position.copy(center).add(offset);
  camera.lookAt(center);
}

function addBackgroundStars() {
  var count = 1400;
  var posArr = new Float32Array(count * 3);
  for (var i = 0; i < count; i++) {
    var u = Math.random() * 2 - 1;
    var th = Math.random() * Math.PI * 2;
    var s = Math.sqrt(Math.max(0, 1 - u * u));
    var r = 2200 + Math.random() * 2300;
    posArr[i * 3] = r * s * Math.cos(th);
    posArr[i * 3 + 1] = r * u;
    posArr[i * 3 + 2] = r * s * Math.sin(th);
  }
  var geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(posArr, 3));
  var mat = new THREE.PointsMaterial({
    color: 0xffffff,
    size: 1.7,
    transparent: true,
    opacity: 0.6,
    sizeAttenuation: true,
    fog: false,
  });
  var stars = new THREE.Points(geo, mat);
  stars.frustumCulled = false;
  backgroundStars = stars;
  scene.add(stars);
}

// =============================== 节点与边 ===============================

function makeGlowTexture() {
  var c = document.createElement("canvas");
  c.width = c.height = 128;
  var ctx = c.getContext("2d");
  var g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.25, "rgba(255,255,255,0.55)");
  g.addColorStop(0.6, "rgba(255,255,255,0.14)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
}

function createNodeGroup(n, pos) {
  var isAuthor = n.type === "author";
  var isExtra = !!n.__extra; // 作者名下额外作品:更小更暗,隐约环绕作者
  var color = isAuthor ? 0x9cc7ff : 0xffd166; // 作者星:蓝白 / 作品星:金色
  var r = isAuthor ? 6 : (isExtra ? 6.2 : 8.5);
  if (!glowTexture) glowTexture = makeGlowTexture();

  var core = new THREE.Mesh(
    new THREE.SphereGeometry(r, 14, 14),
    new THREE.MeshBasicMaterial({ color: color, transparent: true, opacity: isExtra ? 0.7 : 0.95, fog: false })
  );
  core.userData.node = n;
  core.userData.baseR = r;

  var sprite = new THREE.Sprite(
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

  var group = new THREE.Group();
  group.add(core);
  group.add(sprite);
  group.position.copy(pos);
  group.userData.core = core;
  group.userData.sprite = sprite;

  var div = document.createElement("div");
  div.className = "nodelabel";
  div.textContent = n.label;
  var label = new THREE.CSS2DObject(div);
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

function createEdgeLine(e) {
  var isAuthored = e.type === "authored";
  if (!glowTexture) glowTexture = makeGlowTexture();
  var mat;
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
  var geo = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(),
    new THREE.Vector3(),
  ]);
  var line = new THREE.Line(geo, mat);
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
    var trailGeo = new THREE.BufferGeometry();
    trailGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(6), 3));
    trailGeo.setAttribute("color", new THREE.BufferAttribute(new Float32Array(6), 3));
    var trailMat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.95,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      fog: true,
    });
    var trail = new THREE.Line(trailGeo, trailMat);
    trail.frustumCulled = false;
    scene.add(trail);
    flowTrails.push(trail);
  }
}

function initFlowParticles() {
  if (!flowParticles.length) { flowPoints = null; return; }
  var geo = new THREE.BufferGeometry();
  var pos = new Float32Array(flowParticles.length * 3);
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  var mat = new THREE.PointsMaterial({
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

function updateEdgeLines() {
  edgeLines.forEach(function (line) {
    var e = line.userData.edge;
    var pa = positions[e.source];
    var pb = positions[e.target];
    if (!pa || !pb) { line.visible = false; return; }
    line.visible = true;
    var attr = line.geometry.attributes.position;
    attr.setXYZ(0, pa.x, pa.y, pa.z);
    attr.setXYZ(1, pb.x, pb.y, pb.z);
    attr.needsUpdate = true;
  });
}

// =============================== 布局 ===============================

function layoutFor(kind, data) {
  if (kind === "ripple") return rippleLayout(data);
  if (kind === "path") return pathLayout(data);
  if (kind === "author") return authorLayout(data);
  return {};
}

function forceLayoutChunked(ids, edges, callback) {
  // 优先用 Worker 异步计算;不可用时回退到主线程分帧计算
  if (typeof Worker !== "undefined") {
    try {
      var worker = new Worker(new URL("./layout.worker.js", import.meta.url), { type: "module" });
      var done = false;
      worker.onmessage = function (ev) {
        worker.terminate();
        if (done) return;
        done = true;
        var pos = {};
        Object.keys(ev.data.positions || {}).forEach(function (id) {
          var p = ev.data.positions[id];
          pos[id] = new THREE.Vector3(p[0], p[1], p[2]);
        });
        callback(pos);
      };
      worker.onerror = function () {
        worker.terminate();
        if (done) return;
        done = true;
        forceLayoutMainThread(ids, edges, callback);
      };
      worker.postMessage({ ids: ids, edges: edges });
      return;
    } catch (e) { /* Worker 不可用,走主线程回退 */ }
  }
  forceLayoutMainThread(ids, edges, callback);
}

function forceLayoutMainThread(ids, edges, callback) {
  var positions = {};
  ids.forEach(function (id) {
    var u = Math.random() * 2 - 1;
    var th = Math.random() * Math.PI * 2;
    var s = Math.sqrt(Math.max(0, 1 - u * u));
    var r = 320 + Math.random() * 320;
    positions[id] = new THREE.Vector3(r * s * Math.cos(th), r * u, r * s * Math.sin(th));
  });

  var k = 850 / Math.sqrt(ids.length || 1);
  var temp = 0.62;
  var iters = 260;
  var it = 0;

  function tick() {
    var start = Date.now();
    while (it < iters && Date.now() - start < 14) { // 每帧只算一小段,避免卡顿
      runIteration();
      it++;
    }
    if (it < iters) {
      setTimeout(tick, 0);
      return;
    }
    var meanR = 0;
    ids.forEach(function (id) { meanR += positions[id].length(); });
    meanR = meanR / Math.max(ids.length, 1);
    var scale = 520 / Math.max(meanR, 1);
    ids.forEach(function (id) { positions[id].multiplyScalar(scale); });
    callback(positions);
  }

  function runIteration() {
    var disp = {};
    ids.forEach(function (id) { disp[id] = new THREE.Vector3(); });
    for (var i = 0; i < ids.length; i++) {
      for (var j = i + 1; j < ids.length; j++) {
        var a = ids[i], b = ids[j];
        var delta = positions[a].clone().sub(positions[b]);
        var d = Math.max(delta.length(), 0.01);
        var force = (k * k) / d;
        var dir = delta.normalize();
        disp[a].add(dir.clone().multiplyScalar(force));
        disp[b].sub(dir.clone().multiplyScalar(force));
      }
    }
    edges.forEach(function (e) {
      var pa = positions[e.source], pb = positions[e.target];
      if (!pa || !pb) return;
      var delta = pa.clone().sub(pb);
      var d = Math.max(delta.length(), 0.01);
      var force = (d * d) / k;
      var dir = delta.normalize();
      disp[e.source].sub(dir.clone().multiplyScalar(force));
      disp[e.target].add(dir.clone().multiplyScalar(force));
    });
    ids.forEach(function (id) {
      var dl = disp[id].length();
      if (dl < 0.0001) return;
      positions[id].add(disp[id].clone().normalize().multiplyScalar(Math.min(dl, 220) * temp));
      positions[id].multiplyScalar(1 - 0.0035); // gentle pull to center (cluster shape)
    });
    temp = Math.max(0.02, temp * 0.965);
  }

  tick();
}

function rippleLayout(data) {
  var positions = {};
  var centerId = data.centerId;
  var workNodes = data.nodes.filter(function (n) { return n.type === "work"; });

  positions[centerId] = new THREE.Vector3(0, 0, 0);
  var R = 300;
  // 有涟漪连接的节点才排到涟漪球面;作者名下的额外作品(无链接)留在作者周围形成星云
  var echoIds = {};
  echoIds[centerId] = true;
  data.edges.forEach(function (e) {
    if (e.type !== "echo") return;
    echoIds[e.source] = true;
    echoIds[e.target] = true;
  });
  // 中点 phi 分布:避免节点落在极点,小数量时也不会排成一条线
  var neighbors = workNodes.filter(function (n) { return n.id !== centerId && echoIds[n.id]; });
  neighbors.forEach(function (n, i) {
    var phi = Math.acos(1 - 2 * (i + 0.5) / Math.max(neighbors.length, 1));
    var theta = i * 2.399963;
    positions[n.id] = new THREE.Vector3(
      R * Math.sin(phi) * Math.cos(theta),
      R * Math.cos(phi),
      R * Math.sin(phi) * Math.sin(theta)
    );
  });
  // 作者星靠近其作品
  data.edges.forEach(function (e) {
    if (e.type !== "authored") return;
    var wpos = positions[e.source];
    if (wpos && !positions[e.target]) {
      if (wpos.length() < 1) {
        positions[e.target] = new THREE.Vector3(0, -110, 0);
        return;
      }
      // 作者放到自己作品的外侧(半径略大于作品轨道),绝不会夹在两部作品之间
      var dir = wpos.clone().normalize();
      var perp = new THREE.Vector3().crossVectors(dir, new THREE.Vector3(0, 1, 0));
      if (perp.lengthSq() < 0.0001) perp.set(1, 0, 0);
      perp.normalize();
      positions[e.target] = dir
        .multiplyScalar(345)
        .add(perp.multiplyScalar(35))
        .add(new THREE.Vector3(0, 25, 0));
    }
  });
  // 额外作品:围绕各自作者形成小球状星云(位置随机,隐约环绕)
  workNodes.forEach(function (n) {
    if (n.id === centerId || echoIds[n.id] || positions[n.id]) return;
    var apos = positions[n.author_id];
    if (!apos) return;
    var r = 110 + Math.random() * 70;
    var u = Math.random() * 2 - 1;
    var th = Math.random() * Math.PI * 2;
    var s = Math.sqrt(Math.max(0, 1 - u * u));
    positions[n.id] = new THREE.Vector3(
      apos.x + r * s * Math.cos(th),
      apos.y + r * u,
      apos.z + r * s * Math.sin(th)
    );
  });
  return positions;
}

function authorLayout(data) {
  var positions = {};
  var authorNode = data.nodes.filter(function (n) { return n.type === "author"; })[0];
  var works = data.nodes.filter(function (n) { return n.type === "work"; });
  if (authorNode) positions[authorNode.id] = new THREE.Vector3(0, 0, 0);
  var R = 320;
  works.forEach(function (w, i) {
    var y = 1 - (i / Math.max(works.length - 1, 1)) * 2;
    var rr = Math.sqrt(Math.max(0, 1 - y * y));
    var th = i * 2.399963;
    positions[w.id] = new THREE.Vector3(R * rr * Math.cos(th), R * y, R * rr * Math.sin(th));
  });
  return positions;
}

function pathLayout(data) {
  var positions = {};
  var order = data.pathOrder || [];
  var n = order.length;
  order.forEach(function (id, i) {
    positions[id] = new THREE.Vector3(
      (i - (n - 1) / 2) * 300,
      Math.sin(i * 1.2) * 50,
      Math.cos(i * 1.2) * 50
    );
  });
  return positions;
}

// =============================== 视图管理 ===============================

function clearScene() {
  // CSS2DRenderer 不会自动移除已离开场景的标签 DOM,需手动清理,否则旧书名残留
  Object.keys(nodeLabels).forEach(function (id) {
    var elm = nodeLabels[id].element;
    if (elm && elm.parentNode) elm.parentNode.removeChild(elm);
  });
  Object.keys(nodeGroups).forEach(function (id) {
    var g = nodeGroups[id];
    scene.remove(g);
    g.traverse(function (obj) {
      if (obj.geometry) obj.geometry.dispose();
      if (obj.material) {
        if (obj.material.map) obj.material.map = null;
        obj.material.dispose();
      }
    });
  });
  edgeLines.forEach(function (l) {
    scene.remove(l);
    l.geometry.dispose();
    l.material.dispose();
  });
  flowTrails.forEach(function (l) {
    scene.remove(l);
    l.geometry.dispose();
    l.material.dispose();
  });
  if (flowPoints) {
    scene.remove(flowPoints);
    flowPoints.geometry.dispose();
    if (flowPoints.material) {
      flowPoints.material.map = null;
      flowPoints.material.dispose();
    }
  }
  nodeGroups = {};
  nodeLabels = {};
  edgeLines = [];
  flowParticles = [];
  flowTrails = [];
  flowPoints = null;
  positions = {};
}

function viewLabel(kind, data) {
  if (kind === "main") return "视图:全图谱";
  if (kind === "ripple") {
    var c = data.nodes.filter(function (n) { return n.id === data.centerId; })[0];
    return "视图:涟漪 · " + (c ? c.label : "");
  }
  if (kind === "author") {
    var a = data.nodes.filter(function (n) { return n.type === "author"; })[0];
    return "视图:作者 · " + (a ? a.label : "");
  }
  return "视图:提及链";
}

function finishView(kind, data, opts) {
  opts = opts || {};
  if (opts.camera) {
    applyCameraState(opts.camera);
  } else if (!opts.preserveCamera) {
    if (kind === "main") {
      cameraState.radius = 1500; cameraState.theta = -Math.PI / 2 + 0.4; cameraState.phi = Math.PI / 2 - 0.18;
    } else if (kind === "ripple") {
      cameraState.radius = 1150; cameraState.theta = -Math.PI / 2; cameraState.phi = Math.PI / 2 - 0.12;
    } else if (kind === "author") {
      cameraState.radius = 1200; cameraState.theta = -Math.PI / 2 + 0.3; cameraState.phi = Math.PI / 2 - 0.15;
    } else {
      cameraState.radius = 1250; cameraState.theta = -Math.PI / 2 + 0.35; cameraState.phi = Math.PI / 2 - 0.15;
    }
    center.set(0, 0, 0); // 切换视图时重置平移
  }
  if (!opts.camera) applyCamera();
  lastInteraction = Date.now();
  currentView = kind;
  if (onViewChange) onViewChange({ kind: kind, label: viewLabel(kind, data) });
}

function buildScene(data) {
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

export function renderView(kind, data, opts) {
  var token = ++viewToken;
  hiddenLabelIds = kind === "main" ? isolatedWorkIds(data) : {};
  if (kind === "ripple") {
    // 额外作品默认不显示标签,悬停时再显示
    data.nodes.forEach(function (n) { if (n.__extra) hiddenLabelIds[n.id] = true; });
  }
  clearScene();
  if (kind === "main") {
    // 分帧布局:大数据量时不阻塞主线程
    forceLayoutChunked(data.nodes.map(function (n) { return n.id; }), data.edges, function (pos) {
      if (token !== viewToken) return; // 期间已切换视图,丢弃本次布局结果
      positions = pos;
      buildScene(data);
      finishView(kind, data, opts);
    });
    return;
  }
  positions = layoutFor(kind, data);
  buildScene(data);
  finishView(kind, data, opts);
}

function isolatedWorkIds(data) {
  var deg = {};
  data.edges.forEach(function (e) {
    if (e.type !== "echo") return;
    deg[e.source] = (deg[e.source] || 0) + 1;
    deg[e.target] = (deg[e.target] || 0) + 1;
  });
  var ids = {};
  data.nodes.forEach(function (n) {
    if (n.type === "work" && !deg[n.id]) ids[n.id] = true;
  });
  return ids;
}

function authorPosFor(wpos) {
  if (currentView === "author") return new THREE.Vector3(0, 0, 0);
  var isRipple = currentView === "ripple";
  if (isRipple) {
    if (wpos.length() < 1) return new THREE.Vector3(0, -110, 0);
    var dir = wpos.clone().normalize();
    var perp = new THREE.Vector3().crossVectors(dir, new THREE.Vector3(0, 1, 0));
    if (perp.lengthSq() < 0.0001) perp.set(1, 0, 0);
    perp.normalize();
    return dir.multiplyScalar(345).add(perp.multiplyScalar(35)).add(new THREE.Vector3(0, 25, 0));
  }
  return wpos.clone().multiplyScalar(0.82);
}

// 即时增删作者节点(不重新跑布局),让"显示作家节点"勾选立即生效
export function toggleAuthorsInView(hidden) {
  if (currentView === "path") return; // 提及链保持纯作品视图
  if (hidden) {
    Object.keys(nodeGroups).forEach(function (id) {
      var g = nodeGroups[id];
      var node = g.userData.core.userData.node;
      if (node.type !== "author") return;
      scene.remove(g);
      g.traverse(function (obj) {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) {
          if (obj.material.map) obj.material.map = null;
          obj.material.dispose();
        }
      });
      var label = nodeLabels[id];
      if (label && label.element && label.element.parentNode) {
        label.element.parentNode.removeChild(label.element);
      }
      delete nodeGroups[id];
      delete nodeLabels[id];
      delete positions[id];
    });
    edgeLines = edgeLines.filter(function (line) {
      if (line.userData.edge.type !== "authored") return true;
      scene.remove(line);
      line.geometry.dispose();
      line.material.dispose();
      return false;
    });
  } else {
    Object.keys(nodeGroups).forEach(function (id) {
      var g = nodeGroups[id];
      var node = g.userData.core.userData.node;
      if (node.type !== "work") return;
      var aid = node.author_id;
      if (!aid || nodeGroups[aid]) return;
      var author = fullData.nodes.filter(function (n) { return n.id === aid; })[0];
      if (!author) return;
      var wpos = positions[id];
      if (!wpos) return;
      var apos = authorPosFor(wpos);
      createNodeGroup(author, apos);
      positions[aid] = apos;
      createEdgeLine({ source: id, target: aid, type: "authored" });
    });
  }
}

// =============================== 交互 ===============================

function bindControls(container) {
  var dom = renderer.domElement;
  var ctl = new AbortController();
  boundCleanups.push(function () { ctl.abort(); });
  function bindEvent(target, type, fn, extra) {
    var o = extra ? Object.assign({ signal: ctl.signal }, extra) : { signal: ctl.signal };
    target.addEventListener(type, fn, o);
  }

  function dist(p1, p2) {
    return Math.sqrt((p1.x - p2.x) * (p1.x - p2.x) + (p1.y - p2.y) * (p1.y - p2.y));
  }

  bindEvent(dom, "pointerdown", function (e) {
    activePointers[e.pointerId] = { x: e.clientX, y: e.clientY };
    dragging = true;
    dragButton = e.button; // 0=左键(平移/选择),2=右键(旋转)
    dragMoved = false;
    lastX = e.clientX; lastY = e.clientY;
    lastInteraction = Date.now();
    if (dom.setPointerCapture) dom.setPointerCapture(e.pointerId);
    dom.style.cursor = "grabbing";
    if (Object.keys(activePointers).length === 2) {
      var ids = Object.keys(activePointers);
      pinchDist = dist(activePointers[ids[0]], activePointers[ids[1]]);
    }
  });
  bindEvent(dom, "pointermove", function (e) {
    if (dragging) {
      var ids = Object.keys(activePointers);
      if (ids.length >= 2 && activePointers[e.pointerId]) {
        // 双指捏合:缩放
        activePointers[e.pointerId] = { x: e.clientX, y: e.clientY };
        dragMoved = true;
        if (ids.length === 2 && pinchDist > 0) {
          var d = dist(activePointers[ids[0]], activePointers[ids[1]]);
          if (d > 0) {
            cameraState.radius *= pinchDist / d;
            cameraState.radius = Math.max(50, Math.min(8000, cameraState.radius));
            pinchDist = d;
            lastInteraction = Date.now();
            applyCamera();
          }
        }
        return;
      }
      var dx = e.clientX - lastX;
      var dy = e.clientY - lastY;
      lastX = e.clientX; lastY = e.clientY;
      if (Math.abs(dx) + Math.abs(dy) > 2) dragMoved = true;
      if (e.pointerType === "touch" || dragButton === 2) {
        // 触摸单指 / 鼠标右键:旋转视角
        cameraState.theta -= dx * 0.005;
        cameraState.phi -= dy * 0.005;
        cameraState.phi = Math.max(0.15, Math.min(Math.PI - 0.15, cameraState.phi));
      } else {
        // 鼠标左键拖拽:平移视角
        panBy(dx, dy);
      }
      applyCamera();
    } else {
      hoverPick(e);
    }
  });
  bindEvent(dom, "pointerup", function (e) {
    delete activePointers[e.pointerId];
    dragging = Object.keys(activePointers).length > 0;
    if (!dragging) dom.style.cursor = "grab";
    lastInteraction = Date.now();
    if (dragButton === 0 && !dragMoved) clickPick(e);
  });
  bindEvent(dom, "pointercancel", function (e) {
    delete activePointers[e.pointerId];
    dragging = Object.keys(activePointers).length > 0;
    dom.style.cursor = "grab";
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
  }, { passive: false });
}

function panBy(dx, dy) {
  var forward = new THREE.Vector3().subVectors(center, camera.position).normalize();
  var right = new THREE.Vector3().crossVectors(forward, new THREE.Vector3(0, 1, 0)).normalize();
  var up = new THREE.Vector3().crossVectors(right, forward).normalize();
  var scale = cameraState.radius * 0.0016;
  center.add(right.clone().multiplyScalar(-dx * scale));
  center.add(up.clone().multiplyScalar(dy * scale));
}

function pickMesh(e) {
  var rect = renderer.domElement.getBoundingClientRect();
  mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
  mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(mouse, camera);
  var meshes = Object.keys(nodeGroups).map(function (id) {
    return nodeGroups[id].userData.core;
  });
  var hits = raycaster.intersectObjects(meshes, false);
  return hits.length ? hits[0].object : null;
}

function hoverPick(e) {
  var mesh = pickMesh(e);
  var id = mesh && mesh.userData.node ? mesh.userData.node.id : null;
  Object.keys(nodeLabels).forEach(function (nid) {
    var label = nodeLabels[nid];
    var elm = label.element;
    elm.classList.toggle("active", nid === id);
    if (label.userData && label.userData.hiddenByDefault) {
      label.visible = nid === id;    // 悬停时临时显示孤岛标签
    }
  });
  renderer.domElement.style.cursor = mesh ? "pointer" : "grab";
  hovering = id != null;
  if (id !== lastHoveredNodeId) {
    lastHoveredNodeId = id;
    if (id && onNodeHover) onNodeHover(id);
  }
}

function clickPick(e) {
  var mesh = pickMesh(e);
  if (mesh && mesh.userData && mesh.userData.node && onNodeClick) {
    onNodeClick(mesh.userData.node.id);
  }
}

function onResize() {
  var container = resizeContainer || el("graph");
  if (!container) return;
  var w = container.clientWidth || window.innerWidth;
  var h = container.clientHeight || window.innerHeight;
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
  boundCleanups.forEach(function (fn) { try { fn(); } catch (e) { /* ignore */ } });
  boundCleanups = [];
  clearScene();
  if (scene && backgroundStars) {
    scene.remove(backgroundStars);
    backgroundStars.geometry.dispose();
    backgroundStars.material.dispose();
    backgroundStars = null;
  }
  if (renderer) {
    renderer.dispose();
    if (renderer.domElement && renderer.domElement.parentNode) {
      renderer.domElement.parentNode.removeChild(renderer.domElement);
    }
    renderer = null;
  }
  if (labelRenderer) {
    if (labelRenderer.domElement && labelRenderer.domElement.parentNode) {
      labelRenderer.domElement.parentNode.removeChild(labelRenderer.domElement);
    }
    labelRenderer = null;
  }
  scene = null;
  camera = null;
  glowTexture = null;
  resizeContainer = null;
  hiddenLabelIds = {};
}

function animate() {
  animFrameId = requestAnimationFrame(animate);
  var now = Date.now();
    if (!hovering && now - lastInteraction > 1000) {
      cameraState.theta += 0.0016;
      applyCamera();
    }
  var t = now * 0.001;
  Object.keys(nodeGroups).forEach(function (id) {
    var g = nodeGroups[id];
    var sprite = g.userData.sprite;
    var phase = sprite.userData.phase;
    var base = sprite.userData.baseOpacity || 0.55;
    sprite.material.opacity = base * (0.76 + 0.45 * (0.5 + 0.5 * Math.sin(t * 2.1 + phase)));
    var core = g.userData.core;
    core.scale.setScalar(1 + 0.07 * Math.sin(t * 1.4 + phase));
  });
    // 流动"流星":头部光点 + 向后渐隐的光尾,沿 ECHO 边从 source 流向 target
    if (flowPoints && flowParticles.length) {
      var attr = flowPoints.geometry.attributes.position;
      flowParticles.forEach(function (p, i) {
        var pa = positions[p.source];
        var pb = positions[p.target];
        if (!pa || !pb) {
          attr.setXYZ(i, 0, -10000, 0);
          return;
        }
        var progress = (now * p.speed + p.phase) % 1;
        var hx = pa.x + (pb.x - pa.x) * progress;
        var hy = pa.y + (pb.y - pa.y) * progress;
        var hz = pa.z + (pb.z - pa.z) * progress;
        attr.setXYZ(i, hx, hy, hz);
        var trail = flowTrails[i];
        if (trail) {
          var tailT = Math.max(0, progress - 0.14); // 光尾长度约为边的 14%
          var tPos = trail.geometry.attributes.position;
          tPos.setXYZ(0, hx, hy, hz);
          tPos.setXYZ(
            1,
            pa.x + (pb.x - pa.x) * tailT,
            pa.y + (pb.y - pa.y) * tailT,
            pa.z + (pb.z - pa.z) * tailT
          );
          tPos.needsUpdate = true;
          var tCol = trail.geometry.attributes.color;
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
