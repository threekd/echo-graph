// 图谱视图编排:过滤、主图谱、涟漪、作者视图、路径
import { renderView, getCameraState } from "./renderer.js";
import { workDetail, expansion, findPath } from "./api.js";

let stateRef = null; // 由 App 注入 ref(始终指向最新 { state, dispatch })

export function setStateRef(ref) {
  stateRef = ref;
}

function getState() {
  return stateRef && stateRef.current ? stateRef.current.state : { fullData: { nodes: [], edges: [] } };
}

function dispatch(a) {
  if (stateRef && stateRef.current) stateRef.current.dispatch(a);
}

function failToast(err) {
  dispatch({ type: "SET_TOAST", msg: "请求失败:" + (err && err.message ? " " + err.message : "") });
}

function findNode(id) {
  return getState().fullData.nodes.filter((n) => n.id === id)[0];
}

// 佚名(Anonymous)不是真实作者:隐藏其作者节点,让每部佚名作品独立显示,
// 避免共享的"佚名"星把互不相关的作品连成中枢。数据层保持不变。
function isAnonymousAuthor(n) {
  return !!n && n.type === "author" && (n.originalName === "Anonymous" || n.label === "佚名");
}

// ---- URL 状态同步:视图/过滤/扩散级数自动写入 hash,浏览器前进/后退可导航 ----
// 相机位置不随拖动写入(避免历史记录刷屏),由分享链接(getShareHash)携带最新相机。
let lastWrittenHash = null;

function buildHash(opts, includeCam) {
  const st = getState();
  const cam = getCameraState();
  const view = (opts && opts.view) || st.currentView;
  const parts = [];
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
export function getShareHash() {
  return buildHash({}, true);
}

// 将当前视图/过滤状态写入 URL(不含相机)
export function syncUrl(opts) {
  const hash = buildHash(opts || {}, false);
  if (location.hash.replace(/^#/, "") !== hash) {
    lastWrittenHash = "#" + hash;
    location.hash = hash;
  }
}

// 供 App 判断 hashchange 是否由自身写入(避免重复渲染/相机被重置)
export function isSelfWrittenHash() {
  return location.hash === lastWrittenHash;
}

// 默认规则:隐藏名下作品不超过 1 部、且无提及关系的孤岛作者(连同作品)
export function filterSingleWorkAuthors(data) {
  const workCount = {};
  const deg = {};
  const authorHasEcho = {};
  data.nodes.forEach((n) => {
    if (n.type !== "work" || !n.author_id) return;
    workCount[n.author_id] = (workCount[n.author_id] || 0) + 1;
  });
  data.edges.forEach((e) => {
    if (e.type !== "echo") return;
    deg[e.source] = (deg[e.source] || 0) + 1;
    deg[e.target] = (deg[e.target] || 0) + 1;
  });
  data.nodes.forEach((n) => {
    if (n.type === "work" && n.author_id && (deg[n.id] || 0) > 0) {
      authorHasEcho[n.author_id] = true;
    }
  });
  const hidden = {};
  data.nodes.forEach((n) => {
    if (n.type !== "author") return;
    const total = workCount[n.id] || 0;
    if (!authorHasEcho[n.id] && total <= 1) hidden[n.id] = true;
  });
  const ids = {};
  data.nodes.forEach((n) => {
    if (n.type === "author") {
      if (!hidden[n.id] && !isAnonymousAuthor(n)) ids[n.id] = true;
    } else if (n.type === "work") {
      if (!hidden[n.author_id]) ids[n.id] = true;
    }
  });
  return {
    nodes: data.nodes.filter((n) => !!ids[n.id]),
    edges: data.edges.filter((e) => ids[e.source] && ids[e.target]),
  };
}

// 原有"隐藏孤岛星"勾选框逻辑:隐藏无提及关系的作品
export function filterIslands(data) {
  const deg = {};
  data.edges.forEach((e) => {
    if (e.type !== "echo") return;
    deg[e.source] = (deg[e.source] || 0) + 1;
    deg[e.target] = (deg[e.target] || 0) + 1;
  });
  const visibleWork = {};
  const visibleAuthor = {};
  data.nodes.forEach((n) => {
    if (n.type === "work") visibleWork[n.id] = (deg[n.id] || 0) > 0;
  });
  data.nodes.forEach((a) => {
    if (a.type !== "author") return;
    if (isAnonymousAuthor(a)) return; // 佚名节点不显示
    visibleAuthor[a.id] = data.nodes.some((w) => w.type === "work" && w.author_id === a.id && visibleWork[w.id]);
  });
  const nodes = data.nodes.filter((n) => (n.type === "work" ? !!visibleWork[n.id] : !!visibleAuthor[n.id]));
  const ids = {};
  nodes.forEach((n) => { ids[n.id] = true; });
  return {
    nodes,
    edges: data.edges.filter((e) => ids[e.source] && ids[e.target]),
  };
}

function filterAuthorsWith(data, showAuthors) {
  if (showAuthors) return data;
  const ids = {};
  data.nodes.forEach((n) => {
    if (n.type !== "author") ids[n.id] = true;
  });
  return {
    nodes: data.nodes.filter((n) => n.type !== "author"),
    edges: data.edges.filter((e) => ids[e.source] && ids[e.target]),
  };
}

export function renderMain(opts, dataOverride, overrides) {
  const st = getState();
  // dataOverride 用于首次加载(此时 state 尚未更新),同样经过默认过滤
  let data = filterSingleWorkAuthors(dataOverride || st.fullData);
  const hideIslands = overrides && typeof overrides.hideIslands === "boolean" ? overrides.hideIslands : st.hideIslands;
  const showAuthors = overrides && typeof overrides.showAuthors === "boolean" ? overrides.showAuthors : st.showAuthors;
  if (hideIslands) data = filterIslands(data);
  data = filterAuthorsWith(data, showAuthors);
  dispatch({ type: "SET_VIEW", view: "main" });
  dispatch({ type: "SET_VIEW_DATA", data });
  renderView("main", data, opts || {});
  syncUrl({ view: "main", hideIslands, showAuthors });
}

function addAuthorsTo(data) {
  const st = getState();
  if (!st.showAuthors) return data;
  const nodes = data.nodes.slice();
  const edges = data.edges.slice();
  const out = { nodes, edges };
  Object.keys(data).forEach((k) => {
    if (k !== "nodes" && k !== "edges") out[k] = data[k];
  });
  const have = {};
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
  if (!st.hideIslands) {
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

export function renderRipple(detail, hops, opts) {
  const center = detail.work.id;
  const expandHops = Math.max(1, parseInt(hops, 10) || 1);
  dispatch({ type: "SET_RIPPLE_CENTER", id: center });
  dispatch({ type: "SET_EXPAND", value: expandHops });
  dispatch({ type: "SET_VIEW", view: "ripple" });
  const ids = { [center]: true };
  const nodes = [];
  const edges = [];
  detail.mentioned_by.forEach((e) => {
    ids[e.source] = true;
    edges.push({ source: e.source, target: center, type: "echo", evidence: e.evidence, note: e.note });
  });
  detail.mentions.forEach((e) => {
    ids[e.target] = true;
    edges.push({ source: center, target: e.target, type: "echo", evidence: e.evidence, note: e.note });
  });
  Object.keys(ids).forEach((id) => {
    const n = findNode(id);
    if (n) nodes.push(n);
  });
  const data = addAuthorsTo({ nodes, edges, centerId: center });
  dispatch({ type: "SET_VIEW_DATA", data });
  renderView("ripple", data, opts || {});
  syncUrl({
    view: "ripple", id: center, hops: expandHops,
    hideIslands: getState().hideIslands, showAuthors: getState().showAuthors,
  });
}

// 涟漪视图下切换"隐藏孤岛星"等状态时,按当前设置重新渲染(保持相机)
export function reRenderRipple() {
  const st = getState();
  if (st.currentView !== "ripple" || !st.rippleCenter) return;
  const hops = st.expandHops || 1;
  workDetail(st.rippleCenter).then((d) => {
    renderRipple(d, hops, { preserveCamera: true });
    if (hops > 1) expandRippleDebounced(hops);
  }).catch(failToast);
}

export function expandRippleDebounced(hops) {
  if (!getState().rippleCenter) return;
  expansion(getState().rippleCenter, hops)
    .then((data) => {
      data = addAuthorsTo(data);
      dispatch({ type: "SET_VIEW_DATA", data });
      renderView("ripple", data, { preserveCamera: true });
      const works = data.nodes.filter((n) => n.type === "work").length;
      dispatch({ type: "SET_TOAST", msg: hops + " 级扩散 · " + works + " 本书" });
      syncUrl({
        view: "ripple", id: data.centerId, hops,
        hideIslands: getState().hideIslands, showAuthors: getState().showAuthors,
      });
    })
    .catch(failToast);
}

export function renderAuthorView(author) {
  if (isAnonymousAuthor(author)) {
    dispatch({ type: "SET_TOAST", msg: "佚名(Anonymous)节点已隐藏,可直接搜索具体作品" });
    return;
  }
  dispatch({ type: "SET_AUTHOR", id: author.id });
  dispatch({ type: "SET_VIEW", view: "author" });
  const nodes = [author];
  const edges = [];
  getState().fullData.nodes.filter((n) => n.type === "work" && n.author_id === author.id).forEach((w) => {
    nodes.push(w);
    edges.push({ source: w.id, target: author.id, type: "authored" });
  });
  dispatch({ type: "SET_VIEW_DATA", data: { nodes, edges } });
  renderView("author", { nodes, edges }, {});
  syncUrl({
    view: "author", id: author.id,
    hideIslands: getState().hideIslands, showAuthors: getState().showAuthors,
  });
}

export function renderPath(fromId, toId) {
  dispatch({ type: "SET_PATH", from: fromId, to: toId });
  return findPath(fromId, toId).then((result) => {
    if (!result || !result.nodes || !result.nodes.length) return null;
    const nodes = result.nodes.map((id) => findNode(id)).filter(Boolean);
    const edges = result.edges.map((e) => ({
      source: e.source, target: e.target, type: "echo", evidence: e.evidence, note: e.note,
    }));
    dispatch({ type: "SET_VIEW", view: "path" });
    dispatch({ type: "SET_VIEW_DATA", data: { nodes, edges, pathOrder: result.nodes } });
    renderView("path", { nodes, edges, pathOrder: result.nodes }, {});
    syncUrl({
      view: "path", from: fromId, to: toId,
      hideIslands: getState().hideIslands, showAuthors: getState().showAuthors,
    });
    return result;
  }).catch((err) => {
    failToast(err);
    return undefined; // 网络错误与"未找到链"区分开,调用方通过 undefined 判断
  });
}

export function selectNode(id) {
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

export function showNodeDetail(id) {
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

export function buildWorkLookups() {
  const st = getState();
  const workLookup = {};
  const workById = {};
  const options = [];
  const works = st.fullData.nodes.filter((n) => n.type === "work");
  const baseCount = {};
  works.forEach((w) => {
    const k = w.label + " - " + (w.author || "");
    baseCount[k] = (baseCount[k] || 0) + 1;
  });
  works.forEach((w) => {
    const base = w.label + " - " + (w.author || "");
    // 同名同作者的作品用年份消歧,避免查找键互相覆盖
    const key = baseCount[base] > 1 ? base + (w.year ? " (" + w.year + ")" : " (?)") : base;
    workLookup[key] = w.id;
    workById[w.id] = w;
    options.push({ id: w.id, value: key });
  });
  return { workLookup, workById, options };
}
