// 作者视图:作者名下作品为基底,沿 ECHO(无向)向外扩散
import {
  filterAuthorIslands,
  isAnonymousAuthor,
  workAuthorIds,
  maxEchoHops,
} from "../graphData";
import type { GraphData, GraphNode } from "../../store";
import { dispatch, findNode, getState } from "./state";
import { commitView, syncUrl, type ViewOpts } from "./view";

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
  const authorById = new Map<string, GraphNode>();
  fullData.nodes.forEach((n) => {
    if (n.type === "author") authorById.set(n.id, n);
  });
  // 相关作者:扩散到作品的全部作者(含合著者)一并加入视图,供「作家节点」开关控制
  const relatedAuthorIds = new Set<string>([author.id]);
  fullData.nodes.forEach((n) => {
    if (n.type !== "work" || !ids.has(n.id)) return;
    nodes.push(n);
    workAuthorIds(n).forEach((aid) => {
      if (relatedAuthorIds.has(aid)) return;
      const related = authorById.get(aid);
      if (related) {
        relatedAuthorIds.add(aid);
        nodes.push(related);
      }
    });
  });
  const edges: any[] = [];
  // authored 边:ids 中作品的作者归属(去重)
  const authoredKeys = new Set<string>();
  fullData.nodes.forEach((n) => {
    if (n.type !== "work" || !ids.has(n.id)) return;
    workAuthorIds(n).forEach((aid) => {
      if (!relatedAuthorIds.has(aid)) return;
      const key = n.id + "->" + aid;
      if (!authoredKeys.has(key)) {
        authoredKeys.add(key);
        edges.push({ source: n.id, target: aid, type: "authored" });
      }
    });
  });
  fullData.edges.forEach((e) => {
    if (e.type === "echo" && ids.has(e.source) && ids.has(e.target)) edges.push({ ...e });
  });
  return { nodes, edges };
}

// 作者视图的作家节点开关:隐藏相关作者,但保留中心作者作为视图锚点
// (其 authored 边随之保留;相关作者的 authored 边被过滤)
function filterRelatedAuthors(data: GraphData, keepAuthorId: string): GraphData {
  const visibleIds: Record<string, boolean> = {};
  data.nodes.forEach((n) => {
    if (n.type !== "author" || n.id === keepAuthorId) visibleIds[n.id] = true;
  });
  return {
    nodes: data.nodes.filter((n) => visibleIds[n.id]),
    edges: data.edges.filter((e) => visibleIds[e.source] && visibleIds[e.target]),
  };
}

export function renderAuthorView(author: GraphNode, opts?: ViewOpts) {
  if (isAnonymousAuthor(author)) {
    dispatch({ type: "SET_TOAST", msg: "佚名(Anonymous)节点已隐藏,可直接搜索具体作品" });
    return;
  }
  const showIslands = opts && typeof opts.showIslands === "boolean" ? opts.showIslands : getState().showIslands;
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
  if (!showAuthors) data = filterRelatedAuthors(data, author.id); // 隐藏相关作者,保留中心锚点
  if (!showIslands) data = filterAuthorIslands(data); // 作者视图隐藏孤岛作品
  commitView("author", data, opts || {});
  syncUrl({
    view: "author", id: author.id, hops,
    showIslands, showAuthors,
  });
}

export function expandAuthorDebounced(hops: number) {
  const st = getState();
  const author = st.currentAuthorId ? findNode(st.currentAuthorId) : undefined;
  if (!author) return;
  dispatch({ type: "SET_EXPAND", value: hops });
  let data = authorViewData(author, hops, st.fullData);
  if (!st.showAuthors) data = filterRelatedAuthors(data, author.id);
  if (!st.showIslands) data = filterAuthorIslands(data); // 作者视图隐藏孤岛作品
  dispatch({ type: "SET_VIEW_DATA", data });
  const works = data.nodes.filter((n) => n.type === "work").length;
  dispatch({ type: "SET_TOAST", msg: hops + " 级扩散 · " + works + " 本书" });
  syncUrl({
    view: "author", id: author.id, hops,
    showIslands: st.showIslands, showAuthors: st.showAuthors,
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
