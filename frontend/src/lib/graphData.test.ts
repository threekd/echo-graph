import { describe, expect, it } from "vitest";
import {
  buildWorkLookups,
  filterAuthorsWith,
  filterIslands,
  filterSingleWorkAuthors,
  isAnonymousAuthor,
} from "./graphData";

function node(id: string, type: string, extra: any = {}): any {
  return { id, type, label: id, ...extra };
}

const authors = [
  node("a1", "author"),
  node("a2", "author"),
  node("anon", "author", { originalName: "Anonymous" }),
];
const works = [
  node("w1", "work", { author_id: "a1" }),
  node("w2", "work", { author_id: "a1" }),
  node("w3", "work", { author_id: "a2" }),
  node("w4", "work", { author_id: "anon" }),
];
const edges = [
  { source: "w1", target: "w2", type: "echo" },
  { source: "w1", target: "a1", type: "authored" },
  { source: "w2", target: "a1", type: "authored" },
  { source: "w3", target: "a2", type: "authored" },
  { source: "w4", target: "anon", type: "authored" },
];
const data = { nodes: [...authors, ...works], edges };

describe("isAnonymousAuthor", () => {
  it("识别佚名作者节点", () => {
    expect(isAnonymousAuthor(node("x", "author", { originalName: "Anonymous" }))).toBe(true);
    expect(isAnonymousAuthor(node("x", "author", { label: "佚名" }))).toBe(true);
    expect(isAnonymousAuthor(node("x", "work"))).toBe(false);
    expect(isAnonymousAuthor(null)).toBe(false);
  });
});

describe("filterSingleWorkAuthors", () => {
  it("隐藏只有一部作品且无提及关系的作者及其作品,并排除佚名节点", () => {
    const out = filterSingleWorkAuthors(data);
    const ids = out.nodes.map((n) => n.id).sort();
    expect(ids).toEqual(["a1", "w1", "w2"]);
    const kept = new Set(ids);
    expect(out.edges.every((e) => kept.has(e.source) && kept.has(e.target))).toBe(true);
    expect(out.edges).toHaveLength(3);
  });
});

describe("filterIslands", () => {
  it("只保留有提及关系的作品与相关作者", () => {
    const out = filterIslands(data);
    expect(out.nodes.map((n) => n.id).sort()).toEqual(["a1", "w1", "w2"]);
    expect(out.edges.map((e) => `${e.source}->${e.target}`).sort())
      .toEqual(["w1->a1", "w1->w2", "w2->a1"]);
  });
});

describe("filterAuthorsWith", () => {
  it("隐藏作者节点时保留作品与作品间边", () => {
    const out = filterAuthorsWith(data, false);
    expect(out.nodes.every((n) => n.type === "work")).toBe(true);
    expect(out.edges).toEqual([{ source: "w1", target: "w2", type: "echo" }]);
  });

  it("显示作者时原样返回", () => {
    expect(filterAuthorsWith(data, true)).toBe(data);
  });
});

describe("buildWorkLookups", () => {
  it("同名同作者作品用年份消歧", () => {
    const d = {
      nodes: [
        node("x1", "work", { label: "同名", author: "甲", year: 2000 }),
        node("x2", "work", { label: "同名", author: "甲", year: 2010 }),
        node("x3", "work", { label: "唯一", author: "乙", year: 1990 }),
      ],
      edges: [],
    };
    const { workLookup, workById, options } = buildWorkLookups(d);
    expect(workLookup["同名 - 甲 (2000)"]).toBe("x1");
    expect(workLookup["同名 - 甲 (2010)"]).toBe("x2");
    expect(workLookup["唯一 - 乙"]).toBe("x3");
    expect(workById.x2.label).toBe("同名");
    expect(options).toHaveLength(3);
  });
});
