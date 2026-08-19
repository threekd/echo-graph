/* 后端 API 封装(所有请求走这里,便于统一处理) */

async function getJson<T = any>(url: string): Promise<T> {
  const r = await fetch(url);
  return r.json() as Promise<T>;
}

export function loadGraphData(): Promise<any> {
  return getJson("/api/graph");
}

export function loadStats(): Promise<any> {
  return getJson("/api/stats");
}

export function search(q: string): Promise<any> {
  return getJson("/api/search?q=" + encodeURIComponent(q));
}

export function workDetail(id: string): Promise<any> {
  return getJson("/api/work/" + encodeURIComponent(id));
}

export function expansion(id: string, hops: number): Promise<any> {
  return getJson("/api/expansion/" + encodeURIComponent(id) + "?hops=" + hops);
}

export function findPath(from: string, to: string): Promise<any> {
  return getJson("/api/path?from=" + encodeURIComponent(from) + "&to=" + encodeURIComponent(to));
}
