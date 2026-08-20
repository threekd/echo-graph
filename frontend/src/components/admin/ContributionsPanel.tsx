/* 贡献收件箱面板:与前三 Tab 一致的排序/筛选(审核状态列 + 操作列)。 */

import type { ContributionRow } from "../../lib/adminTypes";
import AdminTable from "./AdminTable";

const STATUS_LABEL: Record<string, string> = {
  pending: "待审核",
  approved: "已通过",
  rejected: "已驳回",
};

const COLS = [
  { key: "source_work", label: "源作品" },
  { key: "source_author", label: "源作品作者" },
  { key: "target_work", label: "目标作品" },
  { key: "target_author", label: "目标作品作者" },
  { key: "evidence", label: "原文片段" },
  { key: "evidence_source", label: "出处" },
  { key: "contact", label: "联系方式" },
  { key: "created_at", label: "提交时间" },
  { key: "status", label: "审核状态" },
];

const FILTER_COLS: { key: string; type: "select" | "text" }[] = [
  { key: "status", type: "select" },
  { key: "source_work", type: "text" },
  { key: "target_work", type: "text" },
];

interface Props {
  items: ContributionRow[];
  loading: boolean;
  sort: { key: string; dir: 1 | -1 } | null;
  filters: Record<string, string>;
  textFilters: Record<string, string>;
  onSort: (key: string) => void;
  onFilter: (key: string, value: string) => void;
  onTextFilter: (key: string, value: string) => void;
  onView: (c: ContributionRow) => void;
}

function truncate(s: string, n: number): string {
  return s && s.length > n ? s.slice(0, n) + "…" : (s || "");
}

export default function ContributionsPanel({
  items,
  loading,
  sort,
  filters,
  textFilters,
  onSort,
  onFilter,
  onTextFilter,
  onView,
}: Props) {
  if (loading && items.length === 0) return <p>加载中…</p>;

  const cellValue = (r: ContributionRow, key: string): string => {
    if (key === "status") return STATUS_LABEL[r.status] || r.status;
    if (key === "evidence") return truncate(r.evidence, 60);
    return String(r[key as keyof ContributionRow] ?? "");
  };
  const uniqueValues = (key: string): string[] =>
    Array.from(new Set(items.map((r) => String(r[key as keyof ContributionRow] || "")))).sort();

  return (
    <AdminTable
      kind="contributions"
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
      renderActions={(r) => <button onClick={() => onView(r)}>查看</button>}
    />
  );
}
