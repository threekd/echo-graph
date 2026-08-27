/* 相机模块:球坐标相机状态、视口应用与回传 React store 的节流同步。

   相机状态(cameraState / center)存于 state.ts 的 R,交互模块(controls)、
   布局取景(layout.autoFitViewRadius)与动画循环共用本模块的入口。 */

import * as THREE from "three";
import type { CameraState } from "../../store";
import { AUTO_ROTATE_SPEED, R } from "./state";

export function setOnCameraChange(fn: (cam: CameraState) => void): void {
  R.onCameraChange = fn;
}

export function getCameraState(): CameraState {
  return {
    theta: R.cameraState.theta,
    phi: R.cameraState.phi,
    radius: R.cameraState.radius,
    cx: R.center.x,
    cy: R.center.y,
    cz: R.center.z,
  };
}

// 相机回传 React store(节流:持续交互期间最多每 200ms 一次)
export function syncCameraToStore(): void {
  if (!R.onCameraChange) return;
  const cam = getCameraState();
  if (
    R.lastSyncedCam &&
    Math.abs(cam.theta - R.lastSyncedCam.theta) < 1e-6 &&
    Math.abs(cam.phi - R.lastSyncedCam.phi) < 1e-6 &&
    Math.abs(cam.radius - R.lastSyncedCam.radius) < 1e-4 &&
    Math.abs(cam.cx - R.lastSyncedCam.cx) < 1e-4 &&
    Math.abs(cam.cy - R.lastSyncedCam.cy) < 1e-4 &&
    Math.abs(cam.cz - R.lastSyncedCam.cz) < 1e-4
  ) {
    return;
  }
  const now = Date.now();
  if (now - R.lastCameraSync < 200) return;
  R.lastCameraSync = now;
  R.lastSyncedCam = cam;
  R.onCameraChange(cam);
}

export function applyCameraState(cam: CameraState | null | undefined): void {
  if (!cam) return;
  if (typeof cam.theta === "number") R.cameraState.theta = cam.theta;
  if (typeof cam.phi === "number") R.cameraState.phi = cam.phi;
  if (typeof cam.radius === "number") R.cameraState.radius = cam.radius;
  if (typeof cam.cx === "number") R.center.set(cam.cx, cam.cy || 0, cam.cz || 0);
  applyCamera();
}

export function applyCamera(): void {
  if (!R.camera) return;
  const r = R.cameraState.radius;
  const th = R.cameraState.theta;
  const ph = R.cameraState.phi;
  const offset = new THREE.Vector3(
    r * Math.sin(ph) * Math.cos(th),
    r * Math.cos(ph),
    r * Math.sin(ph) * Math.sin(th)
  );
  R.camera.position.copy(R.center).add(offset);
  R.camera.lookAt(R.center);
}

export function panBy(dx: number, dy: number): void {
  if (!R.camera) return;
  const forward = new THREE.Vector3().subVectors(R.center, R.camera.position).normalize();
  const right = new THREE.Vector3().crossVectors(forward, new THREE.Vector3(0, 1, 0)).normalize();
  const up = new THREE.Vector3().crossVectors(right, forward).normalize();
  const scale = R.cameraState.radius * 0.0016;
  R.center.add(right.clone().multiplyScalar(-dx * scale));
  R.center.add(up.clone().multiplyScalar(dy * scale));
}

// 空闲自动旋转(动画循环每帧调用;悬停/刚交互时由调用方跳过)
export function autoRotate(): void {
  R.cameraState.theta += AUTO_ROTATE_SPEED;
  applyCamera();
}
