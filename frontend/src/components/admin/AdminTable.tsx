/* 星云工坊通用表格:排序、筛选、操作列(纯展示 + 内置 applyAdminQuery 计算)。 */

import { useEffect, useRef, type ReactNode } from "react";
import { applyAdminQuery } from "./query";

export interface AdminCol {
  key: string;
  label: string;
}

interface Props<T> {
  cols: AdminCol[];
  rows: T[];
  filterCols: { key: string; type: "select" | "text" }[];
  filters: Record<string, string>;
  textFilters: Record<string, string>;
  sort: { key: string; dir: 1 | -1 } | null;
  cellValue: (row: T, key: string) => string;
  cellTitle?: (row: T, key: string) => string | undefined;
  renderCell?: (row: T, key: string) => ReactNode; // 自定义单元格渲染(如行内编辑控件)
  uniqueValues: (key: string) => string[];
  onSort: (key: string) => void;
  onFilter: (key: string, value: string) => void;
  onTextFilter: (key: string, value: string) => void;
  renderActions: (row: T) => ReactNode;
  kind: string;
}

export default function AdminTable<T extends object>({
  cols,
  rows,
  filterCols,
  filters,
  textFilters,
  sort,
  cellValue,
  cellTitle,
  renderCell,
  uniqueValues,
  onSort,
  onFilter,
  onTextFilter,
  renderActions,
  kind,
}: Props<T>) {
  const tableRef = useRef<HTMLTableElement | null>(null);

  // 固定筛选行:实测表头行高度,作为筛选行的 sticky 吸附偏移
  useEffect(() => {
    const table = tableRef.current;
    const firstRow = table?.querySelector("thead tr") as HTMLElement | null;
    if (table && firstRow) {
      table.style.setProperty("--filter-sticky-top", firstRow.offsetHeight + "px");
    }
  }, [kind, rows]);

  const visible = applyAdminQuery(rows, {
    filters,
    textFilters,
    sort,
    cellValue,
  });

  return (
    <table id="admin-table" ref={tableRef}>
      <thead>
        <tr>
          {cols.map((c) => {
            const active = sort?.key === c.key;
            const icon = active ? (sort!.dir === 1 ? "▲" : "▼") : "↕";
            return (
              <th
                key={c.key}
                className={"sortable" + (active ? " active" : "")}
                onClick={() => onSort(c.key)}
                title="点击排序(再点切换升降序)"
              >
                {c.label} <span className="sort-icon">{icon}</span>
              </th>
            );
          })}
          <th>操作</th>
        </tr>
        <tr className="filter-row">
          {cols.map((c) => {
            const fc = filterCols.find((f) => f.key === c.key);
            if (!fc) {
              return <td key={c.key} className="filter-cell" />;
            }
            if (fc.type === "select") {
              return (
                <td key={c.key} className="filter-cell">
                  <select
                    value={filters[c.key] || ""}
                    onChange={(e) => onFilter(c.key, e.target.value)}
                    title={'筛选「' + c.label + '」'}
                  >
                    <option value="">全部</option>
                    {uniqueValues(c.key).map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                </td>
              );
            }
            return (
              <td key={c.key} className="filter-cell">
                <input
                  type="text"
                  placeholder={'搜索' + c.label}
                  value={textFilters[c.key] || ""}
                  onChange={(e) => onTextFilter(c.key, e.target.value)}
                  title={'搜索「' + c.label + '」'}
                />
              </td>
            );
          })}
          <td className="filter-cell" />
        </tr>
      </thead>
      <tbody>
        {visible.length === 0 ? (
          <tr><td className="empty-cell" colSpan={cols.length + 1}>无匹配记录</td></tr>
        ) : visible.map((r) => {
          const rec = r as Record<string, unknown>;
          return (
          <tr key={String(rec.id || rec.source_work_id + ":" + rec.target_work_id)} className={rec.deletedAt ? "deleted" : ""}>
            {cols.map((c) => (
              <td key={c.key} title={cellTitle ? cellTitle(r, c.key) : undefined}>
                {renderCell ? renderCell(r, c.key) : cellValue(r, c.key)}
              </td>
            ))}
            <td>{renderActions(r)}</td>
          </tr>
          );
        })}
      </tbody>
    </table>
  );
}
