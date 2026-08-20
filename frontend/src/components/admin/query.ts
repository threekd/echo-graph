/* 数据管理表格的筛选/排序纯逻辑(与渲染解耦,便于单元测试) */

export interface AdminSort {
  key: string;
  dir: 1 | -1;
}

export type DeletedFilter = "all" | "active" | "deleted";

export interface AdminQueryOptions<T extends Record<string, any>> {
  search: string;
  filters: Record<string, string>;
  // 按列文本搜索:对单元格显示值做不区分大小写的包含匹配
  textFilters: Record<string, string>;
  // 删除状态筛选(当前管理页 UI 已移除该筛选框,保留纯函数能力供测试/复用)
  deletedFilter?: DeletedFilter;
  sort: AdminSort | null;
  cellValue: (row: T, key: string) => string;
}

export function applyAdminQuery<T extends Record<string, any>>(
  rows: T[],
  opts: AdminQueryOptions<T>
): T[] {
  const q = opts.search.trim().toLowerCase();
  const df = opts.deletedFilter || "all";
  const searched = q
    ? rows.filter((r) => Object.values(r).some((v) => v != null && String(v).toLowerCase().includes(q)))
    : rows;
  const filtered = searched.filter((r) => {
    for (const [key, val] of Object.entries(opts.filters)) {
      if (val && String(r[key] || "") !== val) return false;
    }
    for (const [key, q] of Object.entries(opts.textFilters)) {
      const ql = q.trim().toLowerCase();
      if (ql && !opts.cellValue(r, key).toLowerCase().includes(ql)) return false;
    }
    if (df === "active" && r.deletedAt) return false;
    if (df === "deleted" && !r.deletedAt) return false;
    return true;
  });
  const out = [...filtered];
  if (opts.sort) {
    const { key, dir } = opts.sort;
    out.sort((a, b) => {
      const ra = a[key];
      const rb = b[key];
      if (typeof ra === "number" && typeof rb === "number") return (ra - rb) * dir;
      const va = opts.cellValue(a, key);
      const vb = opts.cellValue(b, key);
      if (!va && !vb) return 0;
      if (!va) return 1; // 空值恒排最后,不受方向影响
      if (!vb) return -1;
      const na = Number(va);
      const nb = Number(vb);
      const cmp = !Number.isNaN(na) && !Number.isNaN(nb) ? na - nb : va.localeCompare(vb, "zh-Hans-CN");
      return cmp * dir;
    });
  }
  return out;
}
