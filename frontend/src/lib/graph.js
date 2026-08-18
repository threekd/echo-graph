// 图谱视图编排:过滤、主图谱、涟漪、作者视图、路径
import { renderView, getCameraState, applyCameraState, toggleAuthorsInView } from "./renderer.js";
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

function findNode(id) {
  return getState().fullData.nodes.filter((n) => n.id === id)[0];
}

// 默认规则:隐藏名下作品不超过 1 部、且无提及关系的孤岛作者(连同作品)
export function filterSingleWorkAuthors(data) {
  const workCount = {};
  const deg = {};
  data.nodes.forEach((n) => {
    if (n.type !== "work" || !n.author_id) return;
    workCount[n.author_id] = (workCount[n.author_id] || 0) + 1;
  });
  data.edges.forEach((e) => {
    if (e.type !== "echo") return;
    deg[e.source] = (deg[e.source] || 0) + 1;
    deg[e.target] = (deg[e.target] || 0) + 1;
  });
  const hidden = {};
  data.nodes.forEach((n) => {
    if (n.type !== "author") return;
    const total = workCount[n.id] || 0;
    const hasEcho = data.nodes.some((w) => w.type === "work" && w.author_id === n.id && (deg[w.id] || 0) > 0);
    if (!hasEcho && total <= 1) hidden[n.id] = true;
  });
  const ids = {};
  data.nodes.forEach((n) => {
    if (n.type === "author") {
      if (!hidden[n.id]) ids[n.id] = true;
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

function filterAuthors(data) {
  return filterAuthorsWith(data, getState().showAuthors);
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
    edges.push({ source: w.id, target: aid, type: "authored" });
    if (!have[aid]) {
      const an = findNode(aid);
      if (an) { nodes.push(an); have[aid] = true; }
    }
  });
  return out;
}

export function renderRipple(detail) {
  const center = detail.work.id;
  dispatch({ type: "SET_RIPPLE_CENTER", id: center });
  dispatch({ type: "SET_EXPAND", value: 1 });
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
  renderView("ripple", data, {});
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
    });
}

export function renderAuthorView(author) {
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
    return result;
  });
}

export function selectNode(id) {
  const node = findNode(id);
  if (!node) return;
  if (node.type === "work") {
    workDetail(id).then((d) => {
      renderRipple(d);
      dispatch({ type: "SET_PANEL", panel: { type: "work", d } });
    });
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
    });
  } else {
    dispatch({ type: "SET_PANEL", panel: { type: "author", author: node } });
  }
}

export function buildWorkLookups() {
  const st = getState();
  const workLookup = {};
  const workById = {};
  st.fullData.nodes.filter((n) => n.type === "work").forEach((w) => {
    workLookup[w.label + " - " + (w.author || "")] = w.id;
    workById[w.id] = w;
  });
  return { workLookup, workById };
}
