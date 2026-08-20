/* 贡献表单的作品/作者下拉建议文案(纯函数,便于单测)。 */

import type { GraphNode } from "../store";

// 作品:默认"中文名 - 原著标题";原著语言为中文(zh)时仅显示原著标题
export function workSuggestionLabel(n: GraphNode | null | undefined): string {
  if (!n) return "";
  const cn = n.label ? String(n.label) : "";
  const original = n.originalTitle ? String(n.originalTitle) : "";
  if (!original && !cn) return "";
  return n.language === "zh"
    ? (original || cn)
    : (cn && cn !== original ? `${cn} - ${original}` : (original || cn));
}

export function workSuggestionLabels(nodes: GraphNode[]): string[] {
  const seen = new Set<string>();
  nodes.forEach((n) => {
    if (n.type !== "work") return;
    const label = workSuggestionLabel(n);
    if (label) seen.add(label);
  });
  return Array.from(seen).sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
}

// 作者:默认"中文名 - 原文名";国籍为中国(CN)时仅显示原文名
export function authorSuggestionLabel(n: GraphNode | null | undefined): string {
  if (!n) return "";
  const cn = n.label ? String(n.label) : "";
  const original = n.originalName ? String(n.originalName) : "";
  if (!original && !cn) return "";
  return n.nationality === "CN"
    ? (original || cn)
    : (cn && cn !== original ? `${cn} - ${original}` : (original || cn));
}

export function authorSuggestionLabels(nodes: GraphNode[]): string[] {
  const seen = new Set<string>();
  nodes.forEach((n) => {
    if (n.type !== "author") return;
    const label = authorSuggestionLabel(n);
    if (label) seen.add(label);
  });
  return Array.from(seen).sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
}

// 作品的作者展示名列表:优先按 author_ids 解析作者节点,兜底用后端合并的 author 字符串
export function workAuthorNames(
  work: GraphNode | null | undefined,
  authorsById: Record<string, GraphNode>,
): string[] {
  if (!work) return [];
  const ids = Array.isArray(work.author_ids)
    ? work.author_ids.filter((x): x is string => typeof x === "string" && x.length > 0)
    : [];
  const names = ids
    .map((id) => authorSuggestionLabel(authorsById[id]))
    .filter(Boolean);
  if (names.length) return names;
  const merged = work.author ? String(work.author) : "";
  return merged
    ? merged.split("、").map((s) => s.trim()).filter(Boolean)
    : [];
}
