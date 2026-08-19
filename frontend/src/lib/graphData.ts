/* 图谱数据的纯函数(过滤 / 构图),不依赖 React 与渲染器,便于单元测试。 */

import type { GraphData, GraphNode } from "../store";

// 佚名(Anonymous)不是真实作者:隐藏其作者节点,让每部佚名作品独立显示,
// 避免共享的"佚名"星把互不相关的作品连成中枢。数据层保持不变。
export function isAnonymousAuthor(n: GraphNode | null | undefined): boolean {
  return !!n && n.type === "author" && (n.originalName === "Anonymous" || n.label === "佚名");
}

// 默认规则:隐藏名下作品不超过 1 部、且无提及关系的孤岛作者(连同作品)
export function filterSingleWorkAuthors(data: GraphData): GraphData {
  const workCount: Record<string, number> = {};
  const deg: Record<string, number> = {};
  const authorHasEcho: Record<string, boolean> = {};
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
  const hidden: Record<string, boolean> = {};
  data.nodes.forEach((n) => {
    if (n.type !== "author") return;
    const total = workCount[n.id] || 0;
    if (!authorHasEcho[n.id] && total <= 1) hidden[n.id] = true;
  });
  const ids: Record<string, boolean> = {};
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
export function filterIslands(data: GraphData): GraphData {
  const deg: Record<string, number> = {};
  data.edges.forEach((e) => {
    if (e.type !== "echo") return;
    deg[e.source] = (deg[e.source] || 0) + 1;
    deg[e.target] = (deg[e.target] || 0) + 1;
  });
  const visibleWork: Record<string, boolean> = {};
  const visibleAuthor: Record<string, boolean> = {};
  data.nodes.forEach((n) => {
    if (n.type === "work") visibleWork[n.id] = (deg[n.id] || 0) > 0;
  });
  data.nodes.forEach((a) => {
    if (a.type !== "author") return;
    if (isAnonymousAuthor(a)) return; // 佚名节点不显示
    visibleAuthor[a.id] = data.nodes.some((w) => w.type === "work" && w.author_id === a.id && visibleWork[w.id]);
  });
  const nodes = data.nodes.filter((n) => (n.type === "work" ? !!visibleWork[n.id] : !!visibleAuthor[n.id]));
  const ids: Record<string, boolean> = {};
  nodes.forEach((n) => { ids[n.id] = true; });
  return {
    nodes,
    edges: data.edges.filter((e) => ids[e.source] && ids[e.target]),
  };
}

// 作者视图的孤岛过滤:隐藏无 ECHO 提及关系的作品,但始终保留中心作者节点
export function filterAuthorIslands(data: GraphData): GraphData {
  const deg: Record<string, number> = {};
  data.edges.forEach((e) => {
    if (e.type !== "echo") return;
    deg[e.source] = (deg[e.source] || 0) + 1;
    deg[e.target] = (deg[e.target] || 0) + 1;
  });
  const nodes = data.nodes.filter((n) => n.type === "author" || (n.type === "work" && (deg[n.id] || 0) > 0));
  const ids: Record<string, boolean> = {};
  nodes.forEach((n) => { ids[n.id] = true; });
  return {
    nodes,
    edges: data.edges.filter((e) => ids[e.source] && ids[e.target]),
  };
}

export function filterAuthorsWith(data: GraphData, showAuthors: boolean): GraphData {
  if (showAuthors) return data;
  const ids: Record<string, boolean> = {};
  data.nodes.forEach((n) => {
    if (n.type !== "author") ids[n.id] = true;
  });
  return {
    nodes: data.nodes.filter((n) => n.type !== "author"),
    edges: data.edges.filter((e) => ids[e.source] && ids[e.target]),
  };
}

export interface WorkLookups {
  workLookup: Record<string, string>;
  workById: Record<string, GraphNode>;
  options: { id: string; value: string }[];
}

export function buildWorkLookups(data: GraphData): WorkLookups {
  const workLookup: Record<string, string> = {};
  const workById: Record<string, GraphNode> = {};
  const options: { id: string; value: string }[] = [];
  const works = data.nodes.filter((n) => n.type === "work");
  const baseCount: Record<string, number> = {};
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
