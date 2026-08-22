/* 后端 API 封装(所有请求走这里,便于统一处理与类型收敛) */

import type { GraphData } from "../store";

// 浏览空间三元状态:public = 公共星云;mine = 我的星云(私有);
// "space:<userId>" = 星际跃迁后正在浏览的他人星云。
export type Space = "public" | "mine" | `space:${string}`;

export interface SearchHit {
  id: string;
  type: string;
  label: string;
  sub?: string;
}

export interface SearchResponse {
  hits: SearchHit[];
}

export interface StatsResponse {
  authors: number;
  works: number;
  echo_edges: number;
  store: string;
  demo: boolean;
  reviewStatus?: {
    authors: Record<string, number>;
    works: Record<string, number>;
    edges: Record<string, number>;
  };
}

export interface WorkDetailResponse {
  work: Record<string, any>;
  author: Record<string, any> | null;
  authors: Record<string, any>[];
  mentioned_by: Record<string, any>[];
  mentions: Record<string, any>[];
}

export interface PathResponse {
  nodes: string[];
  edges: Record<string, any>[];
}

export interface SpaceRows {
  authors: Record<string, any>[];
  works: Record<string, any>[];
  edges: Record<string, any>[];
}

export interface SpaceJumpResult extends GraphData {
  spaceId: string;
  displayName: string;
}

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  return r.json() as Promise<T>;
}

export function spaceUserId(space: Space): string | null {
  return space.startsWith("space:") ? space.slice("space:".length) : null;
}

// 按空间上下文选择 API 前缀:公共 /api、我的 /api/me、他人星云 /api/space/{userId}。
// 后端空间系列接口(/graph|search|work|expansion|path)共享同一可见性规则。
export function apiRoot(space: Space): string {
  if (space === "mine") return "/api/me";
  const uid = spaceUserId(space);
  if (uid) return "/api/space/" + encodeURIComponent(uid);
  return "/api";
}

export function loadGraphData(space: Space = "public"): Promise<GraphData> {
  return getJson<GraphData>(apiRoot(space) + "/graph");
}

export function loadStats(space: Space = "public"): Promise<StatsResponse> {
  return getJson<StatsResponse>(apiRoot(space) + "/stats");
}

export function search(q: string, space: Space = "public"): Promise<SearchResponse> {
  return getJson<SearchResponse>(apiRoot(space) + "/search?q=" + encodeURIComponent(q));
}

export function workDetail(id: string, space: Space = "public"): Promise<WorkDetailResponse> {
  return getJson<WorkDetailResponse>(apiRoot(space) + "/work/" + encodeURIComponent(id));
}

export function expansion(
  id: string,
  hops: number,
  space: Space = "public"
): Promise<GraphData & { centerId: string }> {
  return getJson<GraphData & { centerId: string }>(
    apiRoot(space) + "/expansion/" + encodeURIComponent(id) + "?hops=" + hops
  );
}

export function findPath(from: string, to: string, space: Space = "public"): Promise<PathResponse> {
  return getJson<PathResponse>(
    apiRoot(space) + "/path?from=" + encodeURIComponent(from) + "&to=" + encodeURIComponent(to)
  );
}

export async function loadMyRows(): Promise<SpaceRows> {
  const r = await fetch("/api/me/data");
  if (!r.ok) throw new Error("加载我的数据失败");
  return r.json() as Promise<SpaceRows>;
}

export async function jumpToRandomSpace(): Promise<SpaceJumpResult> {
  const r = await fetch("/api/space/random/graph");
  if (!r.ok) {
    const d = await r.json().catch(() => null);
    throw new Error((d && d.detail) || "暂无公开星云可跃迁");
  }
  return r.json() as Promise<SpaceJumpResult>;
}
