import { describe, expect, it } from "vitest";
import {
  authorSuggestionLabels,
  workAuthorNames,
  workSuggestionLabels,
} from "./contributeSuggestions";

function node(id: string, type: string, extra: any = {}): any {
  return { id, type, label: id, ...extra };
}

describe("workSuggestionLabels", () => {
  it("非中文作品显示「中文名 - 原著标题」", () => {
    const nodes = [
      node("w1", "work", { label: "局外人", originalTitle: "L'Étranger", language: "fr" }),
    ];
    expect(workSuggestionLabels(nodes)).toEqual(["局外人 - L'Étranger"]);
  });

  it("中文作品仅显示原著标题", () => {
    const nodes = [
      node("w1", "work", { label: "红楼梦", originalTitle: "红楼梦", language: "zh" }),
      node("w2", "work", { label: "西游记", originalTitle: "西游记", language: "zh" }),
    ];
    expect(workSuggestionLabels(nodes)).toEqual(["红楼梦", "西游记"]);
  });

  it("去重并排序", () => {
    const nodes = [
      node("w1", "work", { label: "B书", originalTitle: "Book B", language: "en" }),
      node("w2", "work", { label: "A书", originalTitle: "Book A", language: "en" }),
      node("w3", "work", { label: "B书", originalTitle: "Book B", language: "en" }),
    ];
    expect(workSuggestionLabels(nodes)).toEqual(["A书 - Book A", "B书 - Book B"]);
  });
});

describe("authorSuggestionLabels", () => {
  it("非中国作者显示「中文名 - 原文名」", () => {
    const nodes = [
      node("a1", "author", { label: "加缪", originalName: "Albert Camus", nationality: "FR" }),
    ];
    expect(authorSuggestionLabels(nodes)).toEqual(["加缪 - Albert Camus"]);
  });

  it("中国作者仅显示原文名", () => {
    const nodes = [
      node("a1", "author", { label: "鲁迅", originalName: "鲁迅", nationality: "CN" }),
      node("a2", "author", { label: "老舍", originalName: "老舍", nationality: "CN" }),
    ];
    expect(authorSuggestionLabels(nodes)).toEqual(["老舍", "鲁迅"]);
  });
});

describe("workAuthorNames", () => {
  it("按 author_ids 解析作者展示名(多人、含中国作者规则)", () => {
    const authorsById = {
      a1: { id: "a1", type: "author", label: "加缪", originalName: "Albert Camus", nationality: "FR" },
      a2: { id: "a2", type: "author", label: "鲁迅", originalName: "鲁迅", nationality: "CN" },
    } as any;
    const work = { id: "w1", type: "work", author_ids: ["a1", "a2"] } as any;
    expect(workAuthorNames(work, authorsById)).toEqual(["加缪 - Albert Camus", "鲁迅"]);
  });

  it("author_ids 缺失时回退到后端合并的 author 字符串", () => {
    const work = { id: "w1", type: "work", author: "加缪、某" } as any;
    expect(workAuthorNames(work, {})).toEqual(["加缪", "某"]);
  });

  it("无作者信息返回空数组", () => {
    expect(workAuthorNames({ id: "w1", type: "work" } as any, {})).toEqual([]);
    expect(workAuthorNames(null, {})).toEqual([]);
  });
});
