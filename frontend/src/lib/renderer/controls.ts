/* 交互模块:鼠标/触摸的旋转、平移、缩放、拾取与悬停视觉状态。

   React 侧(GraphCanvas)只做事件委托与命中判定,本模块负责 Three.js
   侧的射线拾取与节点标签/光标状态;底部手势区的单指抑制逻辑见 mobileGestures。 */

import type { GraphNode } from "../../store";
import { el } from "../util";
import { isBottomGestureTouch } from "../mobileGestures";
import { applyCamera, panBy, syncCameraToStore } from "./camera";
import { R } from "./state";

export function bindControls(container: HTMLElement): void {
  const dom = R.renderer!.domElement;
  const ctl = new AbortController();
  R.boundCleanups.push(function () { ctl.abort(); });
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
    R.activePointers[e.pointerId] = { x: e.clientX, y: e.clientY };
    R.dragging = true;
    R.dragButton = e.button; // 0=左键(平移/选择),2=右键(旋转)
    R.lastX = e.clientX; R.lastY = e.clientY;
    R.lastInteraction = Date.now();
    if (dom.setPointerCapture) dom.setPointerCapture(e.pointerId);
    dom.style.cursor = "grabbing";
    if (Object.keys(R.activePointers).length === 2) {
      const ids = Object.keys(R.activePointers);
      R.pinchDist = dist(R.activePointers[ids[0]], R.activePointers[ids[1]]);
      R.pinchMidX = (R.activePointers[ids[0]].x + R.activePointers[ids[1]].x) / 2;
      R.pinchMidY = (R.activePointers[ids[0]].y + R.activePointers[ids[1]].y) / 2;
    } else if (e.pointerType === "touch") {
      // 首个手指落点作为手势区方向判断基准
      R.zoneTouchStartX = e.clientX;
      R.zoneTouchStartY = e.clientY;
      R.zoneVerticalUp = false;
    }
  });
  bindEvent(dom, "pointermove", function (e) {
    if (R.dragging) {
      const ids = Object.keys(R.activePointers);
      if (ids.length >= 2 && R.activePointers[e.pointerId]) {
        // 双指手势:间距变化 → 缩放,中点位移 → 旋转(同时生效)
        R.activePointers[e.pointerId] = { x: e.clientX, y: e.clientY };
        if (ids.length === 2) {
          const a = R.activePointers[ids[0]];
          const b = R.activePointers[ids[1]];
          const d = dist(a, b);
          const mx = (a.x + b.x) / 2;
          const my = (a.y + b.y) / 2;
          if (R.pinchDist > 0 && d > 0) {
            R.cameraState.radius *= R.pinchDist / d; // 开合 → 缩放
            R.cameraState.radius = Math.max(50, Math.min(8000, R.cameraState.radius));
          }
          // 双指整体位移 → 旋转
          R.cameraState.theta -= (mx - R.pinchMidX) * 0.005;
          R.cameraState.phi -= (my - R.pinchMidY) * 0.005;
          R.cameraState.phi = Math.max(0.15, Math.min(Math.PI - 0.15, R.cameraState.phi));
          R.pinchDist = d;
          R.pinchMidX = mx;
          R.pinchMidY = my;
          R.lastInteraction = Date.now();
          applyCamera();
        }
        return;
      }
      // 底部手势区单指:仅抑制"纵向向上主导"的平移(交给呼出栏);
      // 横向平移、双指旋转/缩放不受影响
      if (e.pointerType === "touch" && isBottomGestureTouch()) {
        const cdx = e.clientX - R.zoneTouchStartX;
        const cdy = e.clientY - R.zoneTouchStartY;
        if (!R.zoneVerticalUp && cdy < 0 && Math.abs(cdy) > Math.abs(cdx) * 1.2) {
          R.zoneVerticalUp = true;
        }
        if (R.zoneVerticalUp) {
          R.lastX = e.clientX;
          R.lastY = e.clientY;
          return;
        }
      }
      const dx = e.clientX - R.lastX;
      const dy = e.clientY - R.lastY;
      R.lastX = e.clientX; R.lastY = e.clientY;
      if (R.dragButton === 2) {
        // 鼠标右键:旋转视角
        R.cameraState.theta -= dx * 0.005;
        R.cameraState.phi -= dy * 0.005;
        R.cameraState.phi = Math.max(0.15, Math.min(Math.PI - 0.15, R.cameraState.phi));
      } else {
        // 触摸单指 / 鼠标左键:平移视角
        panBy(dx, dy);
      }
      applyCamera();
    }
  });
  bindEvent(dom, "pointerup", function (e) {
    delete R.activePointers[e.pointerId];
    R.dragging = Object.keys(R.activePointers).length > 0;
    if (!R.dragging) dom.style.cursor = "grab";
    R.pinchDist = 0;
    R.pinchMidX = 0;
    R.pinchMidY = 0;
    const rest = Object.keys(R.activePointers);
    if (rest.length === 1) {
      // 双指抬起一根后,剩余单指继续旋转,同步基准点避免跳变
      R.lastX = R.activePointers[rest[0]].x;
      R.lastY = R.activePointers[rest[0]].y;
    }
    if (Object.keys(R.activePointers).length === 0) R.zoneVerticalUp = false;
    R.lastInteraction = Date.now();
    syncCameraToStore();
  });
  bindEvent(dom, "pointercancel", function (e) {
    delete R.activePointers[e.pointerId];
    R.dragging = Object.keys(R.activePointers).length > 0;
    dom.style.cursor = "grab";
    R.pinchDist = 0;
    R.pinchMidX = 0;
    R.pinchMidY = 0;
    const rest = Object.keys(R.activePointers);
    if (rest.length === 1) {
      R.lastX = R.activePointers[rest[0]].x;
      R.lastY = R.activePointers[rest[0]].y;
    }
    if (Object.keys(R.activePointers).length === 0) R.zoneVerticalUp = false;
    syncCameraToStore();
  });
  bindEvent(dom, "contextmenu", function (e) {
    e.preventDefault(); // 屏蔽右键菜单,右键用于旋转
  });
  bindEvent(container, "wheel", function (e) {
    e.preventDefault();
    R.cameraState.radius *= 1 + e.deltaY * 0.0011;
    R.cameraState.radius = Math.max(50, Math.min(8000, R.cameraState.radius));
    R.lastInteraction = Date.now();
    applyCamera();
    if (R.wheelTimer) window.clearTimeout(R.wheelTimer);
    R.wheelTimer = window.setTimeout(syncCameraToStore, 250);
  }, { passive: false });
}

// 射线拾取:由 React 事件委托调用,返回命中的节点 id
export function pickNode(clientX: number, clientY: number): string | null {
  if (!R.renderer || !R.raycaster || !R.mouse || !R.camera) return null;
  const rect = R.renderer.domElement.getBoundingClientRect();
  R.mouse.x = ((clientX - rect.left) / rect.width) * 2 - 1;
  R.mouse.y = -((clientY - rect.top) / rect.height) * 2 + 1;
  R.raycaster.setFromCamera(R.mouse, R.camera);
  const meshes = Object.keys(R.nodeGroups).map(function (id) {
    return R.nodeGroups[id].userData.hit || R.nodeGroups[id].userData.core;
  });
  const hits = R.raycaster.intersectObjects(meshes, false);
  return hits.length ? (hits[0].object.userData.node as GraphNode).id : null;
}

// 悬停视觉状态(标签激活/孤岛标签临时显示/光标),由 React 事件委托调用
export function setHoveredNode(id: string | null): void {
  if (!R.renderer) return;
  Object.keys(R.nodeLabels).forEach(function (nid) {
    const label = R.nodeLabels[nid];
    const elm = label.element;
    elm.classList.toggle("active", nid === id);
    if (label.userData && label.userData.hiddenByDefault) {
      label.visible = nid === id; // 悬停时临时显示孤岛标签
    }
  });
  R.renderer.domElement.style.cursor = id ? "pointer" : "grab";
  R.hovering = id != null;
}

export function onResize(): void {
  const container = R.resizeContainer || el("graph");
  if (!container || !R.camera || !R.renderer || !R.labelRenderer) return;
  const w = container.clientWidth || window.innerWidth;
  const h = container.clientHeight || window.innerHeight;
  R.camera.aspect = w / h;
  R.camera.updateProjectionMatrix();
  R.renderer.setSize(w, h);
  R.labelRenderer.setSize(w, h);
}
