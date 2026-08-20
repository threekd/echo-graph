// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import AdminTable from "./AdminTable";

afterEach(cleanup);

const cols = [
  { key: "Name_CN", label: "中文名" },
  { key: "nationality", label: "国家" },
];
const filterCols: { key: string; type: "select" | "text" }[] = [{ key: "nationality", type: "select" }];
const rows: any[] = [
  { id: "a1", Name_CN: "甲", nationality: "CN" },
  { id: "a2", Name_CN: "乙", nationality: "US" },
  { id: "a3", Name_CN: "丙", nationality: "CN", deletedAt: "2026-01-01T00:00:00+00:00" },
];
const cellValue = (r: any, k: string) => String(r[k] ?? "");
const uniqueValues = (k: string) =>
  Array.from(new Set(rows.map((r) => String(r[k] || "")))).sort();
const base = {
  cols,
  rows,
  filterCols,
  filters: {},
  textFilters: {},
  sort: null,
  cellValue,
  uniqueValues,
  kind: "authors",
};

describe("AdminTable", () => {
  it("渲染行、操作列与软删除行", () => {
    render(
      <AdminTable
        {...base}
        onSort={vi.fn()}
        onFilter={vi.fn()}
        onTextFilter={vi.fn()}
        renderActions={(r) => <button>{r.deletedAt ? "恢复" : "编辑"}</button>}
      />
    );
    expect(screen.getByText("甲")).toBeTruthy();
    expect(screen.getAllByText("编辑").length).toBe(2);
    expect(screen.getByText("恢复")).toBeTruthy();
  });

  it("点击表头触发排序回调", () => {
    const onSort = vi.fn();
    render(
      <AdminTable
        {...base}
        onSort={onSort}
        onFilter={vi.fn()}
        onTextFilter={vi.fn()}
        renderActions={() => null}
      />
    );
    fireEvent.click(screen.getByText("中文名"));
    expect(onSort).toHaveBeenCalledWith("Name_CN");
  });

  it("筛选下拉按显示值过滤行", () => {
    render(
      <AdminTable
        {...base}
        filters={{ nationality: "US" }}
        onSort={vi.fn()}
        onFilter={vi.fn()}
        onTextFilter={vi.fn()}
        renderActions={() => null}
      />
    );
    expect(screen.queryByText("甲")).toBeNull();
    expect(screen.getByText("乙")).toBeTruthy();
  });
});
