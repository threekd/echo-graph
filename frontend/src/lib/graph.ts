// 图谱视图编排:过滤、主图谱、涟漪、作者视图、路径
import { renderView, getCameraState } from "./renderer";
import { workDetail, expansion, findPath } from "./api";
import {
  isAnonymousAuthor,
  filterSingleWorkAuthors,
  filterIslands,
  filterAuthorsWith,
  buildWorkLookups as buildWorkLookupsPure,
} from "./graphData";
import { initialState, type AppAction, type AppState, type GraphData, type GraphNode } from "../store";

// 纯函数统一来自 graphData.js,这里仅做转发,保证既有调用方兼容
export {
  isAnonymousAuthor,
  filterSingleWorkAuthors,
  filterIslands,
  filterAuthorsWith,
  buildWorkLookupsPure as buildWorkLookups,
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

function findNode(id: string): GraphNode | undefined {
  return getState().fullData.nodes.filter((n) => n.id === id)[0];
}

// ---- URL 状态同步:视图/过滤/扩散级数自动写入 hash,浏览器前进/后退可导航 ----
// 相机位置不随拖动写入(避免历史记录刷屏),由分享链接(getShareHash)携带最新相机。
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
  camera?: any;
}

function buildHash(opts: ViewOpts | undefined, includeCam: boolean): string {
  const st = getState();
  const cam = getCameraState();
  const view = (opts && opts.view) || st.currentView;
  const parts: string[] = [];
  if (view === "ripple") {
    const id = (opts && opts.id) || st.rippleCenter;
    const hops = (opts && opts.hops) || st.expandHops || 1;
    if (id) parts.push("v=ripple:" + id + ":" + hops);
    else parts.push("v=main");
  } else if (view === "author") {
    const id = (opts && opts.id) || st.currentAuthorId;
    if (id) parts.push("v=author:" + id);
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
  if (includeCam && cam) {
    parts.push("cam=" + [cam.theta, cam.phi, cam.radius, cam.cx, cam.cy, cam.cz].map((x) => +x.toFixed(3)).join(","));
  }
  return parts.join("&");
}

// 分享链接:当前视图 + 最新相机位置 + 过滤状态
export function getShareHash(): string {
  return buildHash({}, true);
}

// 将当前视图/过滤状态写入 URL(不含相机)
export function syncUrl(opts: ViewOpts) {
  const hash = buildHash(opts || {}, false);
  if (location.hash.replace(/^#/, "") !== hash) {
    lastWrittenHash = "#" + hash;
    location.hash = hash;
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
  dispatch({ type: "SET_VIEW", view: "main" });
  renderView("main", data, opts || {});
  syncUrl({ view: "main", hideIslands, showAuthors });
}

function addAuthorsTo(data: GraphData, opts?: ViewOpts): GraphData {
  const st = getState();
  const showAuthors = opts && typeof opts.showAuthors === "boolean" ? opts.showAuthors : st.showAuthors;
  const hideIslands = opts && typeof opts.hideIslands === "boolean" ? opts.hideIslands : st.hideIslands;
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
    const aid = w.author_id;
    if (!aid) return;
    const an = findNode(aid);
    if (an && isAnonymousAuthor(an)) return; // 佚名节点不加入涟漪/扩散子图
    edges.push({ source: w.id, target: aid, type: "authored" });
    if (!have[aid]) {
      if (an) { nodes.push(an); have[aid] = true; }
    }
  });
  // 未勾选"隐藏孤岛星"时:把当前视图里每位作者名下的全部作品也展示出来(勾选后回到仅涟漪节点的行为)
  if (!hideIslands) {
    nodes.filter((n) => n.type === "author").forEach((a) => {
      st.fullData.nodes.filter((w) => w.type === "work" && w.author_id === a.id).forEach((w) => {
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
  const expandHops = Math.max(1, parseInt(String(hops || 1), 10) || 1);
  const hideIslands = opts && typeof opts.hideIslands === "boolean" ? opts.hideIslands : getState().hideIslands;
  const showAuthors = opts && typeof opts.showAuthors === "boolean" ? opts.showAuthors : getState().showAuthors;
  dispatch({ type: "SET_RIPPLE_CENTER", id: center });
  dispatch({ type: "SET_EXPAND", value: expandHops });
  dispatch({ type: "SET_VIEW", view: "ripple" });
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
    const n = findNode(id);
    if (n) nodes.push(n);
  });
  const data = addAuthorsTo({ nodes, edges, centerId: center }, { hideIslands, showAuthors });
  renderView("ripple", data, opts || {});
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

export function expandRippleDebounced(hops: number) {
  const center = getState().rippleCenter;
  if (!center) return;
  expansion(center, hops)
    .then((data: any) => {
      const st = getState();
      const viewData = addAuthorsTo(data, { hideIslands: st.hideIslands, showAuthors: st.showAuthors });
      renderView("ripple", viewData, { preserveCamera: true });
      const works = viewData.nodes.filter((n) => n.type === "work").length;
      dispatch({ type: "SET_TOAST", msg: hops + " 级扩散 · " + works + " 本书" });
      syncUrl({
        view: "ripple", id: viewData.centerId, hops,
        hideIslands: st.hideIslands, showAuthors: st.showAuthors,
      });
    })
    .catch(failToast);
}

export function renderAuthorView(author: GraphNode, opts?: ViewOpts) {
  if (isAnonymousAuthor(author)) {
    dispatch({ type: "SET_TOAST", msg: "佚名(Anonymous)节点已隐藏,可直接搜索具体作品" });
    return;
  }
  const hideIslands = opts && typeof opts.hideIslands === "boolean" ? opts.hideIslands : getState().hideIslands;
  const showAuthors = opts && typeof opts.showAuthors === "boolean" ? opts.showAuthors : getState().showAuthors;
  dispatch({ type: "SET_AUTHOR", id: author.id });
  dispatch({ type: "SET_VIEW", view: "author" });
  const nodes: GraphNode[] = [author];
  const edges: any[] = [];
  getState().fullData.nodes.filter((n) => n.type === "work" && n.author_id === author.id).forEach((w) => {
    nodes.push(w);
    edges.push({ source: w.id, target: author.id, type: "authored" });
  });
  renderView("author", { nodes, edges }, {});
  syncUrl({
    view: "author", id: author.id,
    hideIslands, showAuthors,
  });
}

export function renderPath(fromId: string, toId: string, opts?: ViewOpts): Promise<any> {
  dispatch({ type: "SET_PATH", from: fromId, to: toId });
  return findPath(fromId, toId).then((result: any) => {
    if (!result || !result.nodes || !result.nodes.length) return null;
    const nodes = result.nodes.map((id: string) => findNode(id)).filter(Boolean) as GraphNode[];
    const edges = result.edges.map((e: any) => ({
      source: e.source, target: e.target, type: "echo", evidence: e.evidence, note: e.note,
    }));
    dispatch({ type: "SET_VIEW", view: "path" });
    renderView("path", { nodes, edges, pathOrder: result.nodes }, {});
    syncUrl({
      view: "path", from: fromId, to: toId,
      hideIslands: opts && typeof opts.hideIslands === "boolean" ? opts.hideIslands : getState().hideIslands,
      showAuthors: opts && typeof opts.showAuthors === "boolean" ? opts.showAuthors : getState().showAuthors,
    });
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
      dispatch({ type: "SET_PANEL", panel: { type: "work", d } });
    }).catch(failToast);
  } else {
    renderAuthorView(node);
    dispatch({ type: "SET_PANEL", panel: { type: "author", author: node } });
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
