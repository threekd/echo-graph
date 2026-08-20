/* 审计记录面板:与前三 Tab 一致的排序/筛选(审核状态=操作列)。 */

import { useEffect, useState } from "react";
import type { AuditEntry } from "../../lib/adminTypes";
import AdminTable from "./AdminTable";

const ACTION_LABEL: Record<string, string> = {
  create: "新增",
  update: "修改",
  delete: "删除",
  restore: "恢复",
};

const COLS = [
  { key: "ts", label: "时间" },
  { key: "action", label: "审核状态" },
  { key: "kind", label: "类型" },
  { key: "row_id", label: "对象" },
  { key: "detail", label: "详情" },
];

const FILTER_COLS: { key: string; type: "select" | "text" }[] = [
  { key: "action", type: "select" },
  { key: "kind", type: "select" },
  { key: "row_id", type: "text" },
];

interface Props {
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
  sort: { key: string; dir: 1 | -1 } | null;
  filters: Record<string, string>;
  textFilters: Record<string, string>;
  onSort: (key: string) => void;
  onFilter: (key: string, value: string) => void;
  onTextFilter: (key: string, value: string) => void;
}

function truncate(s: string, n: number): string {
  return s && s.length > n ? s.slice(0, n) + "…" : (s || "");
}

export default function AuditPanel({
  authFetch,
  sort,
  filters,
  textFilters,
  onSort,
  onFilter,
  onTextFilter,
}: Props) {
  const [items, setItems] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    authFetch("/api/admin/audit?limit=500")
      .then((r) => r.json())
      .then((d) => {
        if (cancelled) return;
        setItems(d.items || []);
        setLoading(false);
      })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [authFetch]);

  if (loading && items.length === 0) return <p>加载中…</p>;

  const cellValue = (r: AuditEntry, key: string): string => {
    if (key === "action") return ACTION_LABEL[r.action] || r.action;
    if (key === "detail") return truncate(r.detail || "", 40);
    return String(r[key as keyof AuditEntry] ?? "");
  };
  const uniqueValues = (key: string): string[] =>
    Array.from(new Set(items.map((r) => String(r[key as keyof AuditEntry] || "")))).sort();

  return (
    <AdminTable
      kind="audit"
      cols={COLS}
      rows={items}
      filterCols={FILTER_COLS}
      filters={filters}
      textFilters={textFilters}
      sort={sort}
      cellValue={cellValue}
      uniqueValues={uniqueValues}
      onSort={onSort}
      onFilter={onFilter}
      onTextFilter={onTextFilter}
      renderActions={() => null}
    />
  );
}
