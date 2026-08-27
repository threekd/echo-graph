/* Three.js 渲染器的共享可变状态(进程内单例)。

   renderer.ts 拆分为 camera / scene / layout / controls 四个职责模块后,
   模块级可变状态统一收敛到本文件,避免跨模块重复声明与循环依赖。
   R 的字段与旧版 renderer.ts 顶部的模块级变量一一对应,行为不变。 */

import * as THREE from "three";
import { CSS2DObject, CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";
import type { CameraState } from "../../store";

export interface FlowParticle {
  source: string;
  target: string;
  phase: number;
  speed: number;
}

export interface RenderState {
  scene: THREE.Scene | null;
  camera: THREE.PerspectiveCamera | null;
  renderer: THREE.WebGLRenderer | null;
  labelRenderer: CSS2DRenderer | null;
  raycaster: THREE.Raycaster | null;
  mouse: THREE.Vector2 | null;
  nodeGroups: Record<string, THREE.Group>; // id -> THREE.Group
  nodeLabels: Record<string, CSS2DObject>; // id -> CSS2DObject
  edgeLines: THREE.Line[]; // line with userData.edge
  flowParticles: FlowParticle[];
  flowPoints: THREE.Points | null; // 沿 ECHO 边流动的光点(仅数据)
  flowTrails: THREE.Line[]; // 每条 ECHO 边的"流星"光尾(头亮尾暗的短光线)
  positions: Record<string, THREE.Vector3>; // id -> THREE.Vector3
  edgePositionsDirty: boolean; // 边几何是否需重写(布局/视图变更后置位)
  cameraState: { radius: number; theta: number; phi: number };
  center: THREE.Vector3; // 相机注视点(平移时移动它)
  lastInteraction: number;
  dragging: boolean;
  dragButton: number;
  lastX: number;
  lastY: number;
  hovering: boolean; // 鼠标悬停在节点上时暂停自动旋转
  activePointers: Record<string, { x: number; y: number }>; // 触摸多点支持
  pinchDist: number;
  pinchMidX: number; // 双指中点(用于二指平移)
  pinchMidY: number;
  viewToken: number; // 防止异步布局的旧回调覆盖新视图
  hiddenLabelIds: Record<string, boolean>; // 主图谱中默认隐藏标签的孤岛作品
  showWorkLabels: boolean; // 作品节点的文字标签是否显示
  currentKind: string | null; // 当前视图类型(用于同视图增量同步)
  glowTexture: THREE.CanvasTexture | null;
  backgroundStars: THREE.Points | null;
  animFrameId: number | null;
  boundCleanups: (() => void)[]; // dispose 时统一移除的监听
  onCameraChange: ((cam: CameraState) => void) | null; // 由 React 注入
  lastCameraSync: number;
  lastSyncedCam: CameraState | null;
  wheelTimer: number | null;
  resizeContainer: HTMLElement | null;
  // 底部手势区单指触摸:记录起点并判断"纵向向上主导"(交给呼出栏,抑制平移)
  zoneTouchStartX: number;
  zoneTouchStartY: number;
  zoneVerticalUp: boolean;
}

export const R: RenderState = {
  scene: null,
  camera: null,
  renderer: null,
  labelRenderer: null,
  raycaster: null,
  mouse: null,
  nodeGroups: {},
  nodeLabels: {},
  edgeLines: [],
  flowParticles: [],
  flowPoints: null,
  flowTrails: [],
  positions: {},
  edgePositionsDirty: true,
  cameraState: {
    radius: 1500,
    theta: -Math.PI / 2 + 0.4,
    phi: Math.PI / 2 - 0.18,
  },
  center: new THREE.Vector3(0, 0, 0),
  lastInteraction: 0,
  dragging: false,
  dragButton: 0,
  lastX: 0,
  lastY: 0,
  hovering: false,
  activePointers: {},
  pinchDist: 0,
  pinchMidX: 0,
  pinchMidY: 0,
  viewToken: 0,
  hiddenLabelIds: {},
  showWorkLabels: true,
  currentKind: null,
  glowTexture: null,
  backgroundStars: null,
  animFrameId: null,
  boundCleanups: [],
  onCameraChange: null,
  lastCameraSync: 0,
  lastSyncedCam: null,
  wheelTimer: null,
  resizeContainer: null,
  zoneTouchStartX: 0,
  zoneTouchStartY: 0,
  zoneVerticalUp: false,
};

// 移动端渲染开关(窄屏判断)
export const IS_MOBILE_RENDER = window.matchMedia("(max-width: 768px)").matches;
export const AUTO_ROTATE_SPEED = IS_MOBILE_RENDER ? 0.0024 : 0.0016; // 手机端自然转动稍快
