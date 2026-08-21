// 图谱视图编排:过滤、主图谱、涟漪、作者视图、路径
import { workDetail, expansion, findPath } from "./api";
import {
  isAnonymousAuthor,
  filterSingleWorkAuthors,
  filterIslands,
  filterAuthorIslands,
  filterAuthorsWith,
  buildWorkLookups as buildWorkLookupsPure,
  workAuthorIds,
  maxEchoHops,
} from "./graphData";
import { isMobileLayout } from "./mobileGestures";
import {
  initialState,
  type AppAction,
  type AppState,
  type CameraState,
  type GraphData,
  type GraphNode,
} from "../store";

// 纯函数统一来自 graphData.ts,这里仅做转发,保证既有调用方兼容
export {
  isAnonymousAuthor,
  filterSingleWorkAuthors,
  filterIslands,
  filterAuthorsWith,
  buildWorkLookupsPure as buildWorkLookups,
  workAuthorIds,
};

interface StateRef {
  current: { state: AppState; dispatch: (a: AppAction) => void } | null;
}

let stateRef: StateRef | null = null; // 由 App 注入 ref(始终指向最新 { state, dispatch })

export function setStateRef(ref: StateRef) {
  stateRef = ref;
}

function getState(): AppState {
  return stateRef && stateRef.current ? stateRef.current.state : initialState;
}

function dispatch(a: AppAction) {
  if (stateRef && stateRef.current) stateRef.current.dispatch(a);
}

function failToast(err: { message?: string }) {
  dispatch({ type: "SET_TOAST", msg: "请求失败:" + (err && err.message ? " " + err.message : "") });
}

function findNode(id: string, fullData?: GraphData): GraphNode | undefined {
  const fd = fullData || getState().fullData;
  return fd.nodes.filter((n) => n.id === id)[0];
}

function countWorks(authorId: string): number {
  return getState().fullData.nodes.filter(
    (n) => n.type === "work" && workAuthorIds(n).includes(authorId)
  ).length;
}

// ---- URL 状态同步:视图/过滤/扩散级数自动写入 hash,浏览器前进/后退可导航 ----
// 相机位置不写入 URL(避免历史记录刷屏);旧版分享链接中的 cam= 仍由 App 解析兼容。
let lastWrittenHash: string | null = null;

interface ViewOpts {
  view?: string;
  id?: string;
  hops?: number;
  from?: string;
  to?: string;
  hideIslands?: boolean;
  showAuthors?: boolean;
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
function commitView(kind: string, data: GraphData, opts: ViewOpts): void {
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
  const hideIslands = opts && typeof opts.hideIslands === "boolean" ? opts.hideIslands : st.hideIslands;
  const showAuthors = opts && typeof opts.showAuthors === "boolean" ? opts.showAuthors : st.showAuthors;
  if (hideIslands) parts.push("islands=1");
  if (!showAuthors) parts.push("authors=0");
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

export function renderMain(opts: any, dataOverride?: GraphData | null, overrides?: ViewOpts) {
  const st = getState();
  // dataOverride 用于首次加载(此时 state 尚未更新),同样经过默认过滤
  let data = filterSingleWorkAuthors(dataOverride || st.fullData);
  const hideIslands = overrides && typeof overrides.hideIslands === "boolean" ? overrides.hideIslands : st.hideIslands;
  const showAuthors = overrides && typeof overrides.showAuthors === "boolean" ? overrides.showAuthors : st.showAuthors;
  if (hideIslands) data = filterIslands(data);
  data = filterAuthorsWith(data, showAuthors);
  commitView("main", data, opts || {});
  syncUrl({ view: "main", hideIslands, showAuthors });
  // 详情栏内容取决于当前视图:主视图无中心节点,一律清空
  dispatch({ type: "SET_PANEL", panel: { type: "empty" } });
}

function addAuthorsTo(data: GraphData, opts?: ViewOpts): GraphData {
  const st = getState();
  const showAuthors = opts && typeof opts.showAuthors === "boolean" ? opts.showAuthors : st.showAuthors;
  const hideIslands = opts && typeof opts.hideIslands === "boolean" ? opts.hideIslands : st.hideIslands;
  const fullData = opts?.fullData || st.fullData;
  if (!showAuthors) return data;
  const nodes = data.nodes.slice();
  const edges = data.edges.slice();
  const out: GraphData = { nodes, edges };
  Object.keys(data).forEach((k) => {
    if (k !== "nodes" && k !== "edges") out[k] = data[k];
  });
  const have: Record<string, boolean> = {};
  nodes.forEach((n) => { have[n.id] = true; });
  nodes.filter((n) => n.type === "work").forEach((w) => {
    workAuthorIds(w).forEach((aid) => {
      const an = findNode(aid, fullData);
      if (an && isAnonymousAuthor(an)) return; // 佚名节点不加入涟漪/扩散子图
      edges.push({ source: w.id, target: aid, type: "authored" });
      if (!have[aid] && an) {
        nodes.push(an);
        have[aid] = true;
      }
    });
  });
  // 未勾选"隐藏孤岛星"时:把当前视图里每位作者名下的全部作品也展示出来(勾选后回到仅涟漪节点的行为)
  if (!hideIslands) {
    nodes.filter((n) => n.type === "author").forEach((a) => {
      fullData.nodes.filter((w) => w.type === "work" && workAuthorIds(w).includes(a.id)).forEach((w) => {
        if (have[w.id]) return;
        nodes.push({ ...w, __extra: true }); // 作者名下额外作品:环绕作者形成隐约星云
        have[w.id] = true;
        edges.push({ source: w.id, target: a.id, type: "authored" });
      });
    });
  }
  return out;
}

export function renderRipple(detail: any, hops?: number | string, opts?: ViewOpts) {
  const center = detail.work.id;
  const hideIslands = opts && typeof opts.hideIslands === "boolean" ? opts.hideIslands : getState().hideIslands;
  const showAuthors = opts && typeof opts.showAuthors === "boolean" ? opts.showAuthors : getState().showAuthors;
  const fullData = opts?.fullData || getState().fullData;
  // 动态上限:该作品实际可达的最远跳数(无人工上限,后端同样不限)
  const expandMax = Math.max(1, maxEchoHops(fullData, [center]));
  const expandHops = Math.min(Math.max(1, parseInt(String(hops || 1), 10) || 1), expandMax);
  dispatch({ type: "SET_RIPPLE_CENTER", id: center });
  dispatch({ type: "SET_EXPAND_MAX", value: expandMax });
  dispatch({ type: "SET_EXPAND", value: expandHops });
  const ids: Record<string, boolean> = { [center]: true };
  const nodes: GraphNode[] = [];
  const edges: any[] = [];
  detail.mentioned_by.forEach((e: any) => {
    ids[e.source] = true;
    edges.push({ source: e.source, target: center, type: "echo", evidence: e.evidence, note: e.note });
  });
  detail.mentions.forEach((e: any) => {
    ids[e.target] = true;
    edges.push({ source: center, target: e.target, type: "echo", evidence: e.evidence, note: e.note });
  });
  Object.keys(ids).forEach((id) => {
    const n = findNode(id, fullData);
    if (n) nodes.push(n);
  });
  const data = addAuthorsTo({ nodes, edges, centerId: center }, { hideIslands, showAuthors, fullData });
  commitView("ripple", data, opts || {});
  syncUrl({
    view: "ripple", id: center, hops: expandHops,
    hideIslands, showAuthors,
  });
}

// 涟漪视图下切换"隐藏孤岛星"等状态时,按当前设置重新渲染(保持相机)
export function reRenderRipple() {
  const st = getState();
  if (st.currentView !== "ripple" || !st.rippleCenter) return;
  const hops = st.expandHops || 1;
  workDetail(st.rippleCenter).then((d: any) => {
    renderRipple(d, hops, { preserveCamera: true });
    if (hops > 1) expandRippleDebounced(hops);
  }).catch(failToast);
}

export function expandRippleDebounced(hops: number, centerId?: string, fullData?: GraphData) {
  const center = centerId || getState().rippleCenter;
  if (!center) return;
  expansion(center, hops)
    .then((data: any) => {
      const st = getState();
      const viewData = addAuthorsTo(data, {
        hideIslands: st.hideIslands,
        showAuthors: st.showAuthors,
        fullData: fullData || st.fullData,
      });
      dispatch({ type: "SET_VIEW_DATA", data: viewData });
      const works = viewData.nodes.filter((n) => n.type === "work").length;
      dispatch({ type: "SET_TOAST", msg: hops + " 级扩散 · " + works + " 本书" });
      syncUrl({
        view: "ripple", id: viewData.centerId, hops,
        hideIslands: st.hideIslands, showAuthors: st.showAuthors,
      });
    })
    .catch(failToast);
}

// 作者扩散子图:层级 N 时,在作者名下全部作品的基础上,沿 ECHO(无向)向外扩 N-1 跳
export function authorViewData(author: GraphNode, hops: number, fullData: GraphData): GraphData {
  const outHops = Math.max(0, hops - 1);
  const works = fullData.nodes.filter((n) => n.type === "work" && workAuthorIds(n).includes(author.id));
  const dist = new Map<string, number>();
  const queue: string[] = [];
  works.forEach((w) => { dist.set(w.id, 0); queue.push(w.id); });
  let qi = 0;
  while (qi < queue.length) {
    const cur = queue[qi++];
    const d = dist.get(cur) ?? 0;
    if (d >= outHops) continue;
    fullData.edges.forEach((e) => {
      if (e.type !== "echo") return;
      const other = e.source === cur ? e.target : (e.target === cur ? e.source : null);
      if (other && !dist.has(other)) {
        dist.set(other, d + 1);
        queue.push(other);
      }
    });
  }
  const ids = new Set(dist.keys());
  const nodes: GraphNode[] = [author];
  fullData.nodes.forEach((n) => {
    if (n.type === "work" && ids.has(n.id)) nodes.push(n);
  });
  const edges: any[] = [];
  works.forEach((w) => edges.push({ source: w.id, target: author.id, type: "authored" }));
  fullData.edges.forEach((e) => {
    if (e.type === "echo" && ids.has(e.source) && ids.has(e.target)) edges.push({ ...e });
  });
  return { nodes, edges };
}

export function renderAuthorView(author: GraphNode, opts?: ViewOpts) {
  if (isAnonymousAuthor(author)) {
    dispatch({ type: "SET_TOAST", msg: "佚名(Anonymous)节点已隐藏,可直接搜索具体作品" });
    return;
  }
  const hideIslands = opts && typeof opts.hideIslands === "boolean" ? opts.hideIslands : getState().hideIslands;
  const showAuthors = opts && typeof opts.showAuthors === "boolean" ? opts.showAuthors : getState().showAuthors;
  const fullData = opts?.fullData || getState().fullData;
  // 作者视图:上限 = 该作者名下作品沿 ECHO 可达的最远跳数 + 1(作者层)
  const seeds = fullData.nodes
    .filter((n) => n.type === "work" && workAuthorIds(n).includes(author.id))
    .map((n) => n.id);
  const expandMax = Math.max(1, maxEchoHops(fullData, seeds) + 1);
  const hops = Math.min(opts && typeof opts.hops === "number" ? opts.hops : getState().expandHops, expandMax);
  dispatch({ type: "SET_EXPAND_MAX", value: expandMax });
  dispatch({ type: "SET_EXPAND", value: hops });
  dispatch({ type: "SET_AUTHOR", id: author.id });
  dispatch({ type: "SET_PANEL", panel: { type: "author", author } });
  let data = authorViewData(author, hops, fullData);
  if (hideIslands) data = filterAuthorIslands(data); // 作者视图隐藏孤岛星
  commitView("author", data, opts || {});
  syncUrl({
    view: "author", id: author.id, hops,
    hideIslands, showAuthors,
  });
}

export function expandAuthorDebounced(hops: number) {
  const st = getState();
  const author = st.currentAuthorId ? findNode(st.currentAuthorId) : undefined;
  if (!author) return;
  dispatch({ type: "SET_EXPAND", value: hops });
  let data = authorViewData(author, hops, st.fullData);
  if (st.hideIslands) data = filterAuthorIslands(data); // 作者视图隐藏孤岛星
  dispatch({ type: "SET_VIEW_DATA", data });
  const works = data.nodes.filter((n) => n.type === "work").length;
  dispatch({ type: "SET_TOAST", msg: hops + " 级扩散 · " + works + " 本书" });
  syncUrl({
    view: "author", id: author.id, hops,
    hideIslands: st.hideIslands, showAuthors: st.showAuthors,
  });
}

// 作者视图下切换过滤状态时,按当前设置重新渲染(保持相机)
export function reRenderAuthor(opts?: ViewOpts) {
  const st = getState();
  if (st.currentView !== "author" || !st.currentAuthorId) return;
  const author = st.currentAuthorId ? findNode(st.currentAuthorId) : undefined;
  if (!author) return;
  renderAuthorView(author, { preserveCamera: true, hops: st.expandHops, ...(opts || {}) });
}

export function renderPath(fromId: string, toId: string, opts?: ViewOpts): Promise<any> {
  const fullData = opts?.fullData || getState().fullData;
  dispatch({ type: "SET_PATH", from: fromId, to: toId });
  const fromNode = findNode(fromId, fullData);
  const toNode = findNode(toId, fullData);
  dispatch({
    type: "SET_PATH_INPUTS",
    inputs: {
      from: fromNode ? fromNode.label + " - " + (fromNode.author || "") : "",
      to: toNode ? toNode.label + " - " + (toNode.author || "") : "",
    },
  });
  return findPath(fromId, toId).then((result: any) => {
    if (!result || !result.nodes || !result.nodes.length) return null;
    const nodes = result.nodes.map((id: string) => findNode(id, fullData)).filter(Boolean) as GraphNode[];
    const edges = result.edges.map((e: any) => ({
      source: e.source, target: e.target, type: "echo", evidence: e.evidence, note: e.note,
    }));
    commitView("path", { nodes, edges, pathOrder: result.nodes }, opts || {});
    syncUrl({
      view: "path", from: fromId, to: toId,
      hideIslands: opts && typeof opts.hideIslands === "boolean" ? opts.hideIslands : getState().hideIslands,
      showAuthors: opts && typeof opts.showAuthors === "boolean" ? opts.showAuthors : getState().showAuthors,
    });
    dispatch({ type: "SET_TOAST", msg: `提及链 · ${result.nodes.length} 本书 / ${result.edges.length} 次提及` });
    return result;
  }).catch((err) => {
    failToast(err);
    return undefined; // 网络错误与"未找到链"区分开,调用方通过 undefined 判断
  });
}

export function selectNode(id: string) {
  const node = findNode(id);
  if (!node) return;
  if (isAnonymousAuthor(node)) {
    dispatch({ type: "SET_TOAST", msg: "佚名(Anonymous)节点已隐藏,可直接搜索具体作品" });
    return;
  }
  if (node.type === "work") {
    workDetail(id).then((d) => {
      renderRipple(d);
      // 手机端也保存节点信息供右侧上划查看,但不自动呼出(Panel 按 isMobileLayout 控制)
      dispatch({ type: "SET_PANEL", panel: { type: "work", d } });
      dispatch({ type: "SET_TOAST", msg: "已展开《" + node.label + "》的涟漪", kind: "success" });
    }).catch(failToast);
  } else {
    renderAuthorView(node);
    dispatch({
      type: "SET_TOAST",
      msg: "视图:作者 · " + node.label + "(" + countWorks(node.id) + " 部作品)",
      kind: "success",
    });
  }
}

export function showNodeDetail(id: string) {
  const node = findNode(id);
  if (!node) return;
  if (node.type === "work") {
    workDetail(id).then((d) => {
      dispatch({ type: "SET_PANEL", panel: { type: "work", d } });
    }).catch(failToast);
  } else {
    dispatch({ type: "SET_PANEL", panel: { type: "author", author: node } });
  }
}
