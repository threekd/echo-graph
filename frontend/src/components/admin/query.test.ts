import { describe, expect, it } from "vitest";
import { applyAdminQuery } from "./query";

const authors = [
  { id: "a1", Name_CN: "加缪", originalName: "Albert Camus", reviewStatus: "reviewed", nationality: "CN", birthYear: 1920, deletedAt: "" },
  { id: "a2", Name_CN: "乙", originalName: "Author B", reviewStatus: "draft", nationality: "US", birthYear: 1900, deletedAt: "" },
  { id: "a3", Name_CN: "丙", originalName: "Author C", reviewStatus: "draft", nationality: "", birthYear: 1930, deletedAt: "2026-01-01T00:00:00+00:00" },
];

const cellValue = (r: any, key: string): string => String(r[key] ?? "");

const base = { search: "", filters: {}, textFilters: {}, deletedFilter: "all" as const, sort: null, cellValue };

describe("applyAdminQuery", () => {
  it("按关键字搜索", () => {
    const rows = applyAdminQuery(authors, { ...base, search: "加缪" });
    expect(rows.map((r) => r.id)).toEqual(["a1"]);
  });

  it("按列精确筛选", () => {
    const rows = applyAdminQuery(authors, {
      ...base,
      filters: { reviewStatus: "draft" },
    });
    expect(rows.map((r) => r.id).sort()).toEqual(["a2", "a3"]);
  });

  it("删除状态筛选", () => {
    expect(applyAdminQuery(authors, { ...base, deletedFilter: "active" }).map((r) => r.id).sort())
      .toEqual(["a1", "a2"]);
    expect(applyAdminQuery(authors, { ...base, deletedFilter: "deleted" }).map((r) => r.id))
      .toEqual(["a3"]);
  });

  it("按字符串升降序排序且空值恒排最后", () => {
    const asc = applyAdminQuery(authors, {
      ...base,
      sort: { key: "nationality", dir: 1 },
    });
    expect(asc.map((r) => r.id)).toEqual(["a1", "a2", "a3"]);
    const desc = applyAdminQuery(authors, {
      ...base,
      sort: { key: "nationality", dir: -1 },
    });
    expect(desc.map((r) => r.id)).toEqual(["a2", "a1", "a3"]);
  });

  it("数值列按数字排序", () => {
    const rows = applyAdminQuery(authors, {
      ...base,
      sort: { key: "birthYear", dir: 1 },
    });
    expect(rows.map((r) => r.id)).toEqual(["a2", "a1", "a3"]);
  });

  it("按列文本模糊匹配(不区分大小写)", () => {
    const rows = applyAdminQuery(authors, {
      ...base,
      textFilters: { Name_CN: "加缪" },
    });
    expect(rows.map((r) => r.id)).toEqual(["a1"]);
    const rows2 = applyAdminQuery(authors, {
      ...base,
      textFilters: { originalName: "camus" },
    });
    expect(rows2.map((r) => r.id)).toEqual(["a1"]);
  });

  it("文本筛选按显示值匹配(作品作者名/涟漪作品标题)", () => {
    const works = [
      { id: "w1", Title_CN: "局外人", author_id: "a1" },
      { id: "w2", Title_CN: "鼠疫", author_id: "a2" },
    ];
    const workCellValue = (r: any, key: string): string => {
      if (key === "author_id") {
        return String(r.author_id || "")
          .split(",")
          .map((id: string) => (id === "a1" ? "加缪" : "乙"))
          .join("、");
      }
      return String(r[key] ?? "");
    };
    const byAuthor = applyAdminQuery(works, {
      ...base,
      textFilters: { author_id: "加缪" },
      cellValue: workCellValue,
    });
    expect(byAuthor.map((r) => r.id)).toEqual(["w1"]);

    const edges = [
      { id: "e1", source_work_id: "w1", target_work_id: "w2" },
      { id: "e2", source_work_id: "w2", target_work_id: "w1" },
    ];
    const worksById: Record<string, any> = { w1: { Title_CN: "局外人" }, w2: { Title_CN: "鼠疫" } };
    const edgeCellValue = (r: any, key: string): string => {
      const w = worksById[r[key]];
      return w ? w.Title_CN : String(r[key] ?? "");
    };
    const byTitle = applyAdminQuery(edges, {
      ...base,
      textFilters: { source_work_id: "局外人" },
      cellValue: edgeCellValue,
    });
    expect(byTitle.map((r) => r.id)).toEqual(["e1"]);
  });
});
