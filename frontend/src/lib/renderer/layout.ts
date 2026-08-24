/* 布局模块:视图布局编排(力导向 Worker/主线程回退、路径线性排布、自动取景)。

   底层力导向算法见 ../layout.ts(主线程与 layout.worker.ts 共用);
   本模块只做"选哪种布局 + 结果落到 positions + 自动取景"的编排。 */

import * as THREE from "three";
import type { GraphData } from "../../store";
import { createForceLayout, type ForceEdge } from "../layout";
import { applyCamera, syncCameraToStore } from "./camera";
import { IS_MOBILE_RENDER, R } from "./state";

export function layoutFor(kind: string, data: GraphData): Record<string, THREE.Vector3> {
  if (kind === "path") return pathLayout(data);
  return {};
}

export function forceLayoutChunked(
  ids: string[],
  edges: ForceEdge[],
  initial: Record<string, number[]>,
  callback: (pos: Record<string, THREE.Vector3>) => void
): void {
  // 优先用 Worker 异步计算;不可用或超时(8s)时回退到主线程分帧计算(共用 layout.ts 算法)
  if (typeof Worker !== "undefined") {
    let worker: Worker | null = null;
    let done = false;
    try {
      worker = new Worker(new URL("../layout.worker.ts", import.meta.url), { type: "module" });
      const timeout = window.setTimeout(() => {
        if (done) return;
        done = true;
        if (worker) worker.terminate();
        forceLayoutMainThread(ids, edges, initial, callback); // worker 悬挂超时,回退主线程
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
        forceLayoutMainThread(ids, edges, initial, callback);
      };
      worker.postMessage({ ids: ids, edges: edges, positions: initial });
      return;
    } catch { /* Worker 不可用,走主线程回退 */ }
  }
  forceLayoutMainThread(ids, edges, initial, callback);
}

function forceLayoutMainThread(
  ids: string[],
  edges: ForceEdge[],
  initial: Record<string, number[]>,
  callback: (pos: Record<string, THREE.Vector3>) => void
): void {
  const layout = createForceLayout(ids, edges, initial);

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

// 进入节点视图(涟漪/作者/路径)时,按节点包围球自动调整相机距离,
// 手机端避免窄屏横向视野下默认视角过近,桌面端同样按实际布局取景
export function autoFitViewRadius(kind: string): void {
  if (kind === "main" || !R.camera) return;
  let maxR = 0;
  Object.keys(R.positions).forEach(function (id) {
    const r = R.positions[id].length();
    if (r > maxR) maxR = r;
  });
  if (maxR <= 0) return;
  const halfV = (R.camera.fov * Math.PI) / 360;
  const halfH = Math.atan(Math.tan(halfV) * R.camera.aspect);
  const halfFit = Math.min(halfV, halfH); // 窄屏时横向视野是限制维度
  // 取景系数分端:手机 0.8(比完整容纳更近,节点更大);桌面 1.15(留余量)
  const fitScale = IS_MOBILE_RENDER ? 0.8 : 1.15;
  R.cameraState.radius = Math.max(50, Math.min(8000, (maxR / Math.sin(halfFit)) * fitScale));
  applyCamera();
  syncCameraToStore();
}
