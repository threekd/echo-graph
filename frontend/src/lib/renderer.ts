/* Three.js 3D 渲染:组合入口(场景/布局/相机/交互由 renderer/ 子模块提供)。

   职责拆分(原单文件 963 行,按职责收敛到 renderer/ 目录):
   - renderer/state.ts    共享可变状态(单例,原文件顶部的模块级变量)
   - renderer/camera.ts   相机状态、视口应用与回传 React store
   - renderer/scene.ts    星空、节点/边/粒子/标签构建与清理、视图同步
   - renderer/layout.ts   布局编排(力导向 Worker/主线程回退、路径排布、自动取景)
   - renderer/controls.ts 鼠标/触摸交互、射线拾取、悬停视觉状态

   对外 API 不变:initThree / update / disposeThree / pickNode / setHoveredNode /
   setOnCameraChange(GraphCanvas 与 App 的既有 import 保持可用)。 */

import * as THREE from "three";
import { CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";
import type { CameraState, GraphData } from "../store";
import { el } from "./util";
import { applyCamera, applyCameraState, setOnCameraChange } from "./renderer/camera";
import { bindControls, onResize, pickNode, setHoveredNode } from "./renderer/controls";
import { autoFitViewRadius, forceLayoutChunked, layoutFor } from "./renderer/layout";
import {
  addBackgroundStars,
  buildScene,
  clearScene,
  isolatedWorkIds,
  seedPositions,
  syncScene,
  updateEdgeLines,
} from "./renderer/scene";
import { AUTO_ROTATE_SPEED, R } from "./renderer/state";

export { setOnCameraChange, pickNode, setHoveredNode };

// =============================== 初始化 ===============================

export function initThree(containerOrNull?: HTMLElement | null): void {
  const container = containerOrNull || el("graph");
  if (!container) return;
  R.resizeContainer = container;
  const w = container.clientWidth || 900;
  const h = container.clientHeight || 600;

  R.scene = new THREE.Scene();
  R.scene.fog = new THREE.FogExp2(0x05060f, 0.00030);

  R.camera = new THREE.PerspectiveCamera(55, w / h, 1, 12000);
  applyCamera();

  R.renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: "high-performance", // 优先选择高性能 GPU,移动端帧率更稳
  });
  R.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  R.renderer.setSize(w, h);
  R.renderer.domElement.style.position = "absolute";
  R.renderer.domElement.style.top = "0";
  R.renderer.domElement.style.left = "0";
  R.renderer.domElement.style.zIndex = "1";
  R.renderer.domElement.style.cursor = "grab";
  container.appendChild(R.renderer.domElement);

  R.labelRenderer = new CSS2DRenderer();
  R.labelRenderer.setSize(w, h);
  R.labelRenderer.domElement.style.position = "absolute";
  R.labelRenderer.domElement.style.top = "0";
  R.labelRenderer.domElement.style.left = "0";
  R.labelRenderer.domElement.style.pointerEvents = "none";
  R.labelRenderer.domElement.style.zIndex = "2";
  container.appendChild(R.labelRenderer.domElement);

  addBackgroundStars();

  R.raycaster = new THREE.Raycaster();
  R.mouse = new THREE.Vector2();

  bindControls(container);
  window.addEventListener("resize", onResize);
  animate();
}

// =============================== 视图管理 ===============================

// 受控入口:React 持有 viewData/currentView/相机,渲染器只负责按传入数据绘制。
// data.camera 存在时应用该相机(视图切换/深链恢复);不存在则保持当前相机(同视图刷新)。
export function update(kind: string, data: GraphData): void {
  const token = ++R.viewToken;
  const camera = data.camera as CameraState | undefined;
  R.hiddenLabelIds = kind === "main" ? isolatedWorkIds(data) : {};
  if (kind === "ripple") {
    // 额外作品默认不显示标签,悬停时再显示
    data.nodes.forEach(function (n) { if (n.__extra) R.hiddenLabelIds[n.id] = true; });
  }
  const finalize = () => {
    if (camera) applyCameraState(camera);
    R.lastInteraction = Date.now();
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
  if (R.currentKind === kind) {
    // 同视图刷新:增量同步,保持相机与已有节点(涟漪扩散 / 过滤开关切换)
    if (forceKinds) {
      forceLayoutChunked(data.nodes.map(function (n) { return n.id; }), data.edges, seedPositions(data.nodes), function (pos) {
        if (token !== R.viewToken) return;
        R.positions = anchorRipple(pos);
        syncScene(data);
        R.currentKind = kind;
        finalize();
        autoFitViewRadius(kind);
      });
    } else {
      R.positions = layoutFor(kind, data);
      syncScene(data);
      R.currentKind = kind;
      finalize();
      autoFitViewRadius(kind);
    }
    return;
  }
  clearScene();
  if (forceKinds) {
    // 主图谱与作者视图共用力导向布局(Worker 分帧),观感一致
    forceLayoutChunked(data.nodes.map(function (n) { return n.id; }), data.edges, {}, function (pos) {
      if (token !== R.viewToken) return; // 期间已切换视图,丢弃本次布局结果
      R.positions = anchorRipple(pos);
      buildScene(data);
      R.currentKind = kind;
      finalize();
      autoFitViewRadius(kind);
    });
    return;
  }
  R.positions = layoutFor(kind, data);
  buildScene(data);
  R.currentKind = kind;
  finalize();
  autoFitViewRadius(kind);
}

// =============================== 释放与动画 ===============================

// 组件卸载时释放 Three.js 资源(React StrictMode / 热更新下避免重复初始化与泄漏)
export function disposeThree(): void {
  if (R.animFrameId) {
    cancelAnimationFrame(R.animFrameId);
    R.animFrameId = null;
  }
  window.removeEventListener("resize", onResize);
  R.boundCleanups.forEach(function (fn) { try { fn(); } catch { /* ignore */ } });
  R.boundCleanups = [];
  if (R.wheelTimer) {
    window.clearTimeout(R.wheelTimer);
    R.wheelTimer = null;
  }
  clearScene();
  if (R.scene && R.backgroundStars) {
    R.scene.remove(R.backgroundStars);
    R.backgroundStars.geometry.dispose();
    (R.backgroundStars.material as THREE.Material).dispose();
    R.backgroundStars = null;
  }
  if (R.renderer) {
    R.renderer.dispose();
    if (R.renderer.domElement && R.renderer.domElement.parentNode) {
      R.renderer.domElement.parentNode.removeChild(R.renderer.domElement);
    }
  }
  if (R.labelRenderer && R.labelRenderer.domElement && R.labelRenderer.domElement.parentNode) {
    R.labelRenderer.domElement.parentNode.removeChild(R.labelRenderer.domElement);
  }
  R.glowTexture = null;
  R.resizeContainer = null;
  R.hiddenLabelIds = {};
}

function animate(): void {
  R.animFrameId = requestAnimationFrame(animate);
  const now = Date.now();
  if (!R.hovering && now - R.lastInteraction > 1000) {
    R.cameraState.theta += AUTO_ROTATE_SPEED;
    applyCamera();
  }
  const t = now * 0.001;
  Object.keys(R.nodeGroups).forEach(function (id) {
    const g = R.nodeGroups[id];
    const sprite = g.userData.sprite;
    const phase = sprite.userData.phase;
    const base = sprite.userData.baseOpacity || 0.55;
    sprite.material.opacity = base * (0.76 + 0.45 * (0.5 + 0.5 * Math.sin(t * 2.1 + phase)));
    const core = g.userData.core;
    core.scale.setScalar(1 + 0.07 * Math.sin(t * 1.4 + phase));
  });
  // 流动"流星":头部光点 + 向后渐隐的光尾,沿 ECHO 边从 source 流向 target
  if (R.flowPoints && R.flowParticles.length) {
    const attr = R.flowPoints.geometry.attributes.position;
    R.flowParticles.forEach(function (p, i) {
      const pa = R.positions[p.source];
      const pb = R.positions[p.target];
      if (!pa || !pb) {
        attr.setXYZ(i, 0, -10000, 0);
        return;
      }
      const progress = (now * p.speed + p.phase) % 1;
      const hx = pa.x + (pb.x - pa.x) * progress;
      const hy = pa.y + (pb.y - pa.y) * progress;
      const hz = pa.z + (pb.z - pa.z) * progress;
      attr.setXYZ(i, hx, hy, hz);
      const trail = R.flowTrails[i];
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
  if (R.edgePositionsDirty) {
    updateEdgeLines();
    R.edgePositionsDirty = false;
  }
  R.renderer!.render(R.scene!, R.camera!);
  R.labelRenderer!.render(R.scene!, R.camera!);
}
