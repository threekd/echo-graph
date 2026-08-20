/* 审计记录面板:与前三 Tab 一致的排序/筛选(审核状态=操作列)。 */

import { useEffect, useState } from "react";
import type { AuditEntry } from "../../lib/adminTypes";
import AdminTable from "./AdminTable";

const ACTION_LABEL: Record<string, string> = {
  create: "新增",
  update: "修改",
  delete: "删除",
  restore: "恢复",
  approve: "通过",
  reject: "驳回",
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
  { key: "detail", type: "text" },
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

function parseRow(s: string | null | undefined): Record<string, any> | null {
  if (!s) return null;
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
}

function fmtCell(v: any): string {
  if (v === null || v === undefined || v === "") return "(空)";
  return typeof v === "string" ? v : JSON.stringify(v);
}

function AuditDetail({ entry, onClose }: { entry: AuditEntry; onClose: () => void }) {
  const before = parseRow(entry.before);
  const after = parseRow(entry.after);
  const keys = Array.from(
    new Set([...(before ? Object.keys(before) : []), ...(after ? Object.keys(after) : [])])
  );
  const visibleKeys = keys.filter((k) => {
    const b = before ? before[k] : undefined;
    const a = after ? after[k] : undefined;
    if (b !== a) return true; // 修改/恢复/删除时间等变化行
    return (b === undefined && a !== undefined && a !== "") || (a === undefined && b !== undefined && b !== "");
  });
  return (
    <div id="auth-modal">
      <div className="admin-modal-card">
        <h3>审计详情 · {ACTION_LABEL[entry.action] || entry.action} · {entry.kind}</h3>
        <div id="admin-form">
          <label>
            <span>时间</span>
            <input readOnly value={entry.ts || ""} />
          </label>
          <label>
            <span>对象 id</span>
            <input readOnly value={entry.row_id || ""} />
          </label>
          <label className="full">
            <span>摘要</span>
            <textarea readOnly rows={3} value={entry.detail || ""} />
          </label>
        </div>
        {visibleKeys.length > 0 ? (
          <table id="admin-table">
            <thead>
              <tr>
                <th>字段</th>
                <th>修改前</th>
                <th>修改后</th>
              </tr>
            </thead>
            <tbody>
              {visibleKeys.map((k) => (
                <tr key={k}>
                  <td>{k}</td>
                  <td>{before ? fmtCell(before[k]) : "(空)"}</td>
                  <td>{after ? fmtCell(after[k]) : "(空)"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="panel-hint">该记录没有附带前后数据。</p>
        )}
        <div className="admin-modal-actions">
          <button onClick={onClose}>关闭</button>
        </div>
      </div>
    </div>
  );
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
  const [view, setView] = useState<AuditEntry | null>(null);

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
    if (key === "detail") return truncate(r.detail || "", 60);
    return String(r[key as keyof AuditEntry] ?? "");
  };
  const uniqueValues = (key: string): string[] =>
    Array.from(new Set(items.map((r) => String(r[key as keyof AuditEntry] || "")))).sort();

  return (
    <>
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
        renderActions={(r) => (
          <button onClick={() => setView(r)}>查看</button>
        )}
      />
      {view && <AuditDetail entry={view} onClose={() => setView(null)} />}
    </>
  );
}
