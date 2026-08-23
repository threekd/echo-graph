/* 后端 API 封装(所有请求走这里,便于统一处理与类型收敛) */

import type { GraphData } from "../store";
import type { AuthorRow, EdgeRow, WorkRow } from "./adminTypes";

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
  authors: AuthorRow[];
  works: WorkRow[];
  edges: EdgeRow[];
}

export interface SpaceJumpResult extends GraphData {
  spaceId: string;
  displayName: string;
  owner?: OwnerProfile;
}

export interface OwnerProfile {
  username?: string;
  nickname?: string | null;
  bio?: string | null;
}

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  // 统一检查 HTTP 状态:404/500 的错误 JSON 不能当作成功载荷返回,
  // 否则调用方会把 {detail: ...} 当正常数据渲染(与 jumpToRandomSpace / followUser 一致)。
  if (!r.ok) {
    let detail = "请求失败(" + r.status + ")";
    try {
      const d = await r.json();
      if (d && typeof d.detail === "string" && d.detail) detail = d.detail;
      else if (d && typeof d.message === "string" && d.message) detail = d.message;
    } catch {
      /* 非 JSON 错误响应,保留状态码文案 */
    }
    throw new Error(detail);
  }
  return r.json() as Promise<T>;
}

export function spaceUserId(space: Space): string | null {
  return space.startsWith("space:") ? space.slice("space:".length) : null;
}

// 空间状态值 <-> URL hash 参数互转:
// URL 里用 public / mine / <用户id> 表示,状态里用户空间带 "space:" 前缀
export function spaceParamFromState(space: Space): string {
  if (space === "public" || space === "mine") return space;
  return spaceUserId(space) || "public";
}

export function spaceFromParam(param: string | undefined | null): Space | null {
  if (!param) return null;
  if (param === "public" || param === "mine") return param;
  // 用户空间以 UUID 表示(36 位含连字符)
  if (/^[0-9a-fA-F-]{36}$/.test(param)) return `space:${param}`;
  return null;
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

// ---- 关注模型好友 ----

export interface FollowUser {
  id: string;
  username: string;
  nickname: string | null;
  bio: string | null;
  displayName: string;
}

export interface FollowListResponse {
  items: FollowUser[];
}

export interface FollowRelation {
  following: boolean;
  follower: boolean;
}

export function loadFollowing(): Promise<FollowListResponse> {
  return getJson<FollowListResponse>("/api/follow/following");
}

export function loadFollowers(): Promise<FollowListResponse> {
  return getJson<FollowListResponse>("/api/follow/followers");
}

export function followRelation(userId: string): Promise<FollowRelation> {
  return getJson<FollowRelation>("/api/follow/relation/" + encodeURIComponent(userId));
}

export async function followUser(userId: string): Promise<void> {
  const r = await fetch("/api/follow/" + encodeURIComponent(userId), { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => null);
    throw new Error((d && d.detail) || "关注失败");
  }
}

export async function unfollowUser(userId: string): Promise<void> {
  const r = await fetch("/api/follow/" + encodeURIComponent(userId), { method: "DELETE" });
  if (!r.ok) {
    const d = await r.json().catch(() => null);
    throw new Error((d && d.detail) || "取关失败");
  }
}

// 定向跃迁到指定用户星云(好友列表 / 粉丝列表入口)
export function loadSpaceGraph(userId: string): Promise<SpaceJumpResult> {
  return getJson<SpaceJumpResult>("/api/space/" + encodeURIComponent(userId) + "/graph");
}
