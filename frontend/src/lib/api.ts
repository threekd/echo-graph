/* 后端 API 封装(所有请求走这里,便于统一处理与类型收敛) */

import type { GraphData } from "../store";

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

export interface ContributePayload {
  source_work: string;
  target_work: string;
  source_author: string;
  target_author: string;
  evidence: string;
  evidence_source?: string;
  note?: string;
  contact?: string;
}

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  return r.json() as Promise<T>;
}

export function loadGraphData(): Promise<GraphData> {
  return getJson<GraphData>("/api/graph");
}

export function loadStats(): Promise<StatsResponse> {
  return getJson<StatsResponse>("/api/stats");
}

export function search(q: string): Promise<SearchResponse> {
  return getJson<SearchResponse>("/api/search?q=" + encodeURIComponent(q));
}

export function workDetail(id: string): Promise<WorkDetailResponse> {
  return getJson<WorkDetailResponse>("/api/work/" + encodeURIComponent(id));
}

export function expansion(id: string, hops: number): Promise<GraphData & { centerId: string }> {
  return getJson<GraphData & { centerId: string }>(
    "/api/expansion/" + encodeURIComponent(id) + "?hops=" + hops
  );
}

export function findPath(from: string, to: string): Promise<PathResponse> {
  return getJson<PathResponse>("/api/path?from=" + encodeURIComponent(from) + "&to=" + encodeURIComponent(to));
}

export function submitContribution(payload: ContributePayload): Promise<any> {
  return fetch("/api/contribute/echo", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).then((r) => r.json());
}
