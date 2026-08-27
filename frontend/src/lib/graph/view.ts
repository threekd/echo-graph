// URL 状态同步:视图/过滤/扩散级数自动写入 hash,浏览器前进/后退可导航;相机不写 URL
import { isMobileLayout } from "../mobileGestures";
import type { CameraState, GraphData, ReadingFilter } from "../../store";
import { spaceParamFromState, type Space } from "../api";
import { dispatch, getState } from "./state";

// ---- URL 状态同步:视图/过滤/扩散级数自动写入 hash,浏览器前进/后退可导航 ----
// 相机位置不写入 URL(避免历史记录刷屏);旧版分享链接中的 cam= 仍由 App 解析兼容。
let lastWrittenHash: string | null = null;

export interface ViewOpts {
  view?: string;
  id?: string;
  hops?: number;
  from?: string;
  to?: string;
  space?: Space; // 显式指定星云上下文:空间切换时 state 尚未提交,避免 syncUrl 读到旧值
  showIslands?: boolean;
  showAuthors?: boolean;
  showWorkLabels?: boolean;
  readingFilter?: ReadingFilter;
  preserveCamera?: boolean;
  camera?: CameraState;
  fullData?: GraphData; // 首载深链时显式传入刚加载的全量图,避免 state 尚未刷新
}

// 各视图的默认相机(受控化:由 React 侧决定并随 viewData 交给渲染器执行)
const DEFAULT_CAMERA: Record<string, CameraState> = {
  main: { theta: -Math.PI / 2 + 0.4, phi: Math.PI / 2 - 0.18, radius: 1500, cx: 0, cy: 0, cz: 0 },
  ripple: { theta: -Math.PI / 2, phi: Math.PI / 2 - 0.12, radius: 1150, cx: 0, cy: 0, cz: 0 },
  author: { theta: -Math.PI / 2 + 0.3, phi: Math.PI / 2 - 0.15, radius: 1200, cx: 0, cy: 0, cz: 0 },
  path: { theta: -Math.PI / 2 + 0.35, phi: Math.PI / 2 - 0.15, radius: 1250, cx: 0, cy: 0, cz: 0 },
};

// 相机解析(纯函数,便于单测):opts.camera(深链恢复) > 视图默认相机 > 保持当前相机(preserveCamera)
export function resolveViewCamera(kind: string, opts: ViewOpts): CameraState | undefined {
  if (opts.camera) return opts.camera;
  if (opts.preserveCamera) return undefined;
  return DEFAULT_CAMERA[kind];
}

// 受控化提交:视图数据与相机进 React store,渲染由 GraphCanvas 的 effect 驱动。
export function commitView(kind: string, data: GraphData, opts: ViewOpts): void {
  dispatch({ type: "SET_VIEW", view: kind });
  const camera = resolveViewCamera(kind, opts);
  if (camera) {
    dispatch({ type: "SET_CAMERA", camera });
    data = { ...data, camera };
  }
  dispatch({ type: "SET_VIEW_DATA", data });
}

function buildHash(opts: ViewOpts | undefined): string {
  const st = getState();
  const view = (opts && opts.view) || st.currentView;
  const parts: string[] = [];
  if (view === "ripple") {
    const id = (opts && opts.id) || st.rippleCenter;
    const hops = (opts && opts.hops) || st.expandHops || 1;
    if (id) parts.push("v=ripple:" + id + ":" + hops);
    else parts.push("v=main");
  } else if (view === "author") {
    const id = (opts && opts.id) || st.currentAuthorId;
    const hops = (opts && opts.hops) || st.expandHops || 1;
    if (id) parts.push("v=author:" + id + ":" + hops);
    else parts.push("v=main");
  } else if (view === "path") {
    const from = (opts && opts.from) || st.pathFromId;
    const to = (opts && opts.to) || st.pathToId;
    if (from && to) parts.push("v=path:" + from + "," + to);
    else parts.push("v=main");
  } else {
    parts.push("v=main");
  }
  const showIslands = opts && typeof opts.showIslands === "boolean" ? opts.showIslands : st.showIslands;
  const showAuthors = opts && typeof opts.showAuthors === "boolean" ? opts.showAuthors : st.showAuthors;
  const showWorkLabels =
    opts && typeof opts.showWorkLabels === "boolean" ? opts.showWorkLabels : st.showWorkLabels;
  const readingFilter =
    opts && typeof opts.readingFilter === "string" ? opts.readingFilter : st.readingFilter;
  if (!showIslands) parts.push("islands=1");
  if (!showAuthors) parts.push("authors=0");
  if (!showWorkLabels) parts.push("worklabels=0");
  if (readingFilter && readingFilter !== "all") parts.push("reading=" + readingFilter);
  // 当前星云上下文写入 URL:刷新/分享后保持(空间切换用 replaceState,不产生历史条目)
  parts.push("space=" + spaceParamFromState((opts && opts.space) || st.space || "mine"));
  return parts.join("&");
}

// 将当前视图/过滤状态写入 URL(不含相机)
export function syncUrl(opts: ViewOpts) {
  const hash = buildHash(opts || {});
  if (location.hash.replace(/^#/, "") !== hash) {
    lastWrittenHash = "#" + hash;
    if (isMobileLayout()) {
      // 手机端视图变化不产生历史条目:返回由应用层接管(见 App.tsx 的返回处理)
      history.replaceState(null, "", "#" + hash);
    } else {
      location.hash = hash;
    }
  }
}

// 供 App 判断 hashchange 是否由自身写入(避免重复渲染/相机被重置)
export function isSelfWrittenHash(): boolean {
  return location.hash === lastWrittenHash;
}
