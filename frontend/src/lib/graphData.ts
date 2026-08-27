/* 图谱数据的纯函数(过滤 / 构图),不依赖 React 与渲染器,便于单元测试。 */

import type { GraphData, GraphNode, ReadingFilter } from "../store";

// 佚名(Anonymous)不是真实作者:隐藏其作者节点,让每部佚名作品独立显示,
// 避免共享的"佚名"星把互不相关的作品连成中枢。数据层保持不变。
export function isAnonymousAuthor(n: GraphNode | null | undefined): boolean {
  return !!n && n.type === "author" && (n.originalName === "Anonymous" || n.label === "佚名");
}

// 作品的作者 id 列表:兼容新格式 author_ids(数组)与旧格式 author_id(单 id 或逗号分隔串)
export function workAuthorIds(n: GraphNode | null | undefined): string[] {
  if (!n) return [];
  if (Array.isArray(n.author_ids)) {
    return n.author_ids.filter((x: unknown): x is string => typeof x === "string" && x.length > 0);
  }
  const single = n.author_id;
  return single
    ? String(single).split(",").map((s) => s.trim()).filter(Boolean)
    : [];
}

// 默认规则:隐藏名下作品不超过 1 部、且无提及关系的孤岛作者(连同作品)
export function filterSingleWorkAuthors(data: GraphData): GraphData {
  const workCount: Record<string, number> = {};
  const deg: Record<string, number> = {};
  const authorHasEcho: Record<string, boolean> = {};
  data.nodes.forEach((n) => {
    if (n.type !== "work") return;
    workAuthorIds(n).forEach((aid) => {
      workCount[aid] = (workCount[aid] || 0) + 1;
    });
  });
  data.edges.forEach((e) => {
    if (e.type !== "echo") return;
    deg[e.source] = (deg[e.source] || 0) + 1;
    deg[e.target] = (deg[e.target] || 0) + 1;
  });
  data.nodes.forEach((n) => {
    if (n.type !== "work" || (deg[n.id] || 0) <= 0) return;
    workAuthorIds(n).forEach((aid) => {
      authorHasEcho[aid] = true;
    });
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
      const aids = workAuthorIds(n);
      // 无作者(佚名/未关联)的作品始终保留;有作者时任一作者可见即保留
      if (aids.length === 0 || aids.some((aid) => !hidden[aid])) ids[n.id] = true;
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
    visibleAuthor[a.id] = data.nodes.some(
      (w) => w.type === "work" && workAuthorIds(w).includes(a.id) && visibleWork[w.id]
    );
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

// 按阅读状态过滤作品节点(保留作者节点;无 readingStatus 的作品不属于任何具体状态,被过滤)
export function filterWorksByReading(data: GraphData, filter: ReadingFilter): GraphData {
  if (filter === "all") return data;
  const keep: Record<string, boolean> = {};
  data.nodes.forEach((n) => {
    if (n.type !== "work") {
      keep[n.id] = true;
      return;
    }
    if (n.readingStatus === filter) keep[n.id] = true;
  });
  return {
    nodes: data.nodes.filter((n) => keep[n.id]),
    edges: data.edges.filter((e) => keep[e.source] && keep[e.target]),
  };
}

// 从 seed 作品沿 ECHO(无向)扩散能到达的最远跳数(用于节点视图的动态扩散上限)
export function maxEchoHops(data: GraphData, seedIds: string[]): number {
  const adj: Record<string, string[]> = {};
  data.edges.forEach((e) => {
    if (e.type !== "echo") return;
    (adj[e.source] ||= []).push(e.target);
    (adj[e.target] ||= []).push(e.source);
  });
  const dist = new Map<string, number>();
  const queue: string[] = [];
  seedIds.forEach((id) => {
    if (!dist.has(id)) {
      dist.set(id, 0);
      queue.push(id);
    }
  });
  let farthest = 0;
  let qi = 0;
  while (qi < queue.length) {
    const cur = queue[qi++];
    const d = dist.get(cur) ?? 0;
    if (d > farthest) farthest = d;
    (adj[cur] || []).forEach((nb) => {
      if (!dist.has(nb)) {
        dist.set(nb, d + 1);
        queue.push(nb);
      }
    });
  }
  return farthest;
}

// 没有任何 ECHO 提及关系的作品数(用于"隐藏孤岛星"开关的 toast 提示)
export function islandWorkCount(data: GraphData): number {
  const deg: Record<string, number> = {};
  data.edges.forEach((e) => {
    if (e.type !== "echo") return;
    deg[e.source] = (deg[e.source] || 0) + 1;
    deg[e.target] = (deg[e.target] || 0) + 1;
  });
  return data.nodes.filter((n) => n.type === "work" && !(deg[n.id] || 0)).length;
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
