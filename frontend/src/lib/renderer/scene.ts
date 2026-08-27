/* 场景模块:星空背景、节点/边/流动粒子/标签的构建与清理、视图同步。

   只负责"画什么",不负责"摆在哪"(布局)与"怎么交互"(controls);
   布局结果写入 state.ts 的 positions 后由本模块消费。 */

import * as THREE from "three";
import { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import type { GraphData, GraphEdge, GraphNode } from "../../store";
import { MENTION_COLOR } from "../util";
import { R } from "./state";

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

export function addBackgroundStars(): void {
  if (!R.scene) return;
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
  R.backgroundStars = stars;
  R.scene.add(stars);
}

function createNodeGroup(n: GraphNode, pos: THREE.Vector3): void {
  const isAuthor = n.type === "author";
  const isExtra = !!n.__extra; // 作者名下额外作品:更小更暗,隐约环绕作者
  const color = isAuthor ? 0x9cc7ff : 0xffd166; // 作者星:蓝白 / 作品星:金色
  const r = isAuthor ? 6 : (isExtra ? 6.2 : 8.5);
  if (!R.glowTexture) R.glowTexture = makeGlowTexture();

  const core = new THREE.Mesh(
    new THREE.SphereGeometry(r, 14, 14),
    new THREE.MeshBasicMaterial({ color: color, transparent: true, opacity: isExtra ? 0.7 : 0.95, fog: false })
  );
  core.userData.node = n;
  core.userData.baseR = r;

  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: R.glowTexture,
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
  label.userData = { type: n.type };
  if (R.hiddenLabelIds[n.id]) {
    label.visible = false; // 孤岛作品默认不显示文字(CSS2DRenderer 会强制改写 style.display,须用 visible)
    label.userData.hiddenByDefault = true;
  } else if (n.type === "work" && !R.showWorkLabels) {
    label.visible = false; // 取消「显示作品节点」时隐藏作品文字标签(作者标签不受影响)
  }
  group.add(label);

  R.scene!.add(group);
  R.nodeGroups[n.id] = group;
  R.nodeLabels[n.id] = label;
}

function createEdgeLine(e: GraphEdge): void {
  if (!R.scene) return;
  const isAuthored = e.type === "authored";
  if (!R.glowTexture) R.glowTexture = makeGlowTexture();
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
  R.scene.add(line);
  R.edgeLines.push(line);
  if (!isAuthored) {
    R.flowParticles.push({
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
    R.scene.add(trail);
    R.flowTrails.push(trail);
  }
}

function initFlowParticles(): void {
  if (!R.scene || !R.glowTexture) return;
  if (!R.flowParticles.length) { R.flowPoints = null; return; }
  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(R.flowParticles.length * 3);
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  const mat = new THREE.PointsMaterial({
    map: R.glowTexture,
    color: 0x9ff6ff,
    size: 14,
    transparent: true,
    opacity: 0.95,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    fog: false,
    sizeAttenuation: true,
  });
  R.flowPoints = new THREE.Points(geo, mat);
  R.flowPoints.frustumCulled = false;
  R.scene.add(R.flowPoints);
}

export function updateEdgeLines(): void {
  R.edgeLines.forEach(function (line) {
    const e = line.userData.edge as GraphEdge;
    const pa = R.positions[e.source];
    const pb = R.positions[e.target];
    if (!pa || !pb) { line.visible = false; return; }
    line.visible = true;
    const attr = line.geometry.attributes.position as THREE.BufferAttribute;
    attr.setXYZ(0, pa.x, pa.y, pa.z);
    attr.setXYZ(1, pb.x, pb.y, pb.z);
    attr.needsUpdate = true;
  });
}

function disposeGroup(g: THREE.Group): void {
  R.scene?.remove(g);
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
  const label = R.nodeLabels[id];
  if (label) {
    const elm = label.element;
    if (elm && elm.parentNode) elm.parentNode.removeChild(elm);
    delete R.nodeLabels[id];
  }
  const g = R.nodeGroups[id];
  if (g) {
    disposeGroup(g);
    delete R.nodeGroups[id];
  }
}

function clearEdges(): void {
  R.edgeLines.forEach(function (l) {
    R.scene?.remove(l);
    l.geometry.dispose();
    (l.material as THREE.Material).dispose();
  });
  R.flowTrails.forEach(function (l) {
    R.scene?.remove(l);
    l.geometry.dispose();
    (l.material as THREE.Material).dispose();
  });
  if (R.flowPoints) {
    R.scene?.remove(R.flowPoints);
    R.flowPoints.geometry.dispose();
    if (R.flowPoints.material) {
      const mat = R.flowPoints.material as THREE.PointsMaterial;
      mat.map = null;
      mat.dispose();
    }
  }
  R.edgeLines = [];
  R.flowParticles = [];
  R.flowTrails = [];
  R.flowPoints = null;
}

function clearNodes(): void {
  Object.keys(R.nodeLabels).forEach(function (id) {
    const elm = R.nodeLabels[id].element;
    if (elm && elm.parentNode) elm.parentNode.removeChild(elm);
  });
  Object.keys(R.nodeGroups).forEach(function (id) {
    disposeGroup(R.nodeGroups[id]);
  });
  R.nodeGroups = {};
  R.nodeLabels = {};
}

export function clearScene(): void {
  clearNodes();
  clearEdges();
  R.positions = {};
  R.edgePositionsDirty = true;
}

// 同视图增量更新:保留已有节点组与相机,只增删差异节点、重建边
export function syncScene(data: GraphData): void {
  const keep: Record<string, boolean> = {};
  data.nodes.forEach(function (n) { keep[n.id] = true; });
  Object.keys(R.nodeGroups).forEach(function (id) {
    if (!keep[id]) removeNodeGroup(id);
  });
  data.nodes.forEach(function (n) {
    const p = R.positions[n.id] || new THREE.Vector3();
    if (R.nodeGroups[n.id]) {
      R.nodeGroups[n.id].position.copy(p);
      const label = R.nodeLabels[n.id];
      if (label) {
        if (R.hiddenLabelIds[n.id]) {
          label.visible = false;
          label.userData.hiddenByDefault = true;
        } else if (label.userData && label.userData.hiddenByDefault) {
          label.visible = true;
          delete label.userData.hiddenByDefault;
        } else if (n.type === "work" && !R.showWorkLabels) {
          label.visible = false;
        } else if (n.type === "work" && R.showWorkLabels) {
          label.visible = true;
        }
      }
    } else {
      createNodeGroup(n, p);
    }
  });
  clearEdges();
  data.edges.forEach(createEdgeLine);
  initFlowParticles();
  R.edgePositionsDirty = true; // 边已重建,下一帧用最新布局填充几何
}

export function buildScene(data: GraphData): void {
  data.nodes.forEach(function (n) {
    if (!R.positions[n.id]) {
      R.positions[n.id] = new THREE.Vector3(
        Math.random() * 120 - 60,
        Math.random() * 120 - 60,
        Math.random() * 120 - 60
      );
    }
    createNodeGroup(n, R.positions[n.id]);
  });
  data.edges.forEach(createEdgeLine);
  initFlowParticles();
  R.edgePositionsDirty = true;
}

// 同视图刷新时用旧布局位置作为力导向初始种子,避免每次扩散节点整体跳位
export function seedPositions(nodes: GraphNode[]): Record<string, number[]> {
  const seed: Record<string, number[]> = {};
  nodes.forEach(function (n) {
    const p = R.positions[n.id];
    if (p) seed[n.id] = [p.x, p.y, p.z];
  });
  return seed;
}

export function isolatedWorkIds(data: GraphData): Record<string, boolean> {
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
