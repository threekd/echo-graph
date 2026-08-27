import { describe, expect, it } from "vitest";
import {
  buildWorkLookups,
  filterAuthorsWith,
  filterAuthorIslands,
  filterIslands,
  filterSingleWorkAuthors,
  filterWorksByReading,
  islandWorkCount,
  isAnonymousAuthor,
  maxEchoHops,
  workAuthorIds,
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

describe("workAuthorIds", () => {
  it("兼容 author_ids 数组、author_id 单值与逗号分隔串", () => {
    expect(workAuthorIds(node("x", "work", { author_ids: ["a1", "a2"] }))).toEqual(["a1", "a2"]);
    expect(workAuthorIds(node("x", "work", { author_id: "a1, a2" }))).toEqual(["a1", "a2"]);
    expect(workAuthorIds(node("x", "work", { author_id: "a1" }))).toEqual(["a1"]);
    expect(workAuthorIds(node("x", "work"))).toEqual([]);
    expect(workAuthorIds(null)).toEqual([]);
  });

  it("过滤空值,重复值保留(去重由后端保证)", () => {
    expect(workAuthorIds(node("x", "work", { author_ids: ["a1", "", "a1"] }))).toEqual(["a1", "a1"]);
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

  it("多作者作品:任一作者可见即保留,单作品无提及的合著作者被隐藏", () => {
    const data = {
      nodes: [
        node("a1", "author"),
        node("a2", "author"),
        node("w1", "work", { author_id: "a1" }),
        node("w2", "work", { author_ids: ["a1", "a2"] }),
      ],
      edges: [],
    };
    const out = filterSingleWorkAuthors(data);
    // a1 有 2 部作品 -> 可见;a2 仅合著 w2 一部且无提及 -> 隐藏;w2 因 a1 可见而保留
    expect(out.nodes.map((n) => n.id).sort()).toEqual(["a1", "w1", "w2"]);
  });
});

describe("filterIslands", () => {
  it("只保留有提及关系的作品与相关作者", () => {
    const out = filterIslands(data);
    expect(out.nodes.map((n) => n.id).sort()).toEqual(["a1", "w1", "w2"]);
    expect(out.edges.map((e) => `${e.source}->${e.target}`).sort())
      .toEqual(["w1->a1", "w1->w2", "w2->a1"]);
  });

  it("多作者作品:作者仅在无提及的合著作品中时被隐藏", () => {
    const data = {
      nodes: [
        node("a1", "author"),
        node("a2", "author"),
        node("w1", "work", { author_ids: ["a1"] }),
        node("w2", "work", { author_ids: ["a1", "a2"] }),
        node("w3", "work", { author_ids: ["a2"] }),
        node("w4", "work", { author_ids: ["a1"] }),
      ],
      edges: [
        { source: "w1", target: "w4", type: "echo" },
        { source: "w1", target: "a1", type: "authored" },
      ],
    };
    // w1/w4 有提及 -> a1 可见;w2(合著)/w3 无提及 -> 隐藏,连带 a2 无可见作品 -> 隐藏
    const out = filterIslands(data);
    expect(out.nodes.map((n) => n.id).sort()).toEqual(["a1", "w1", "w4"]);
  });
});

describe("filterWorksByReading", () => {
  const readingData = {
    nodes: [
      node("a1", "author"),
      node("a2", "author"),
      node("w1", "work", { author_id: "a1", readingStatus: "read" }),
      node("w2", "work", { author_id: "a1", readingStatus: "unread" }),
      node("w3", "work", { author_id: "a2", readingStatus: "read" }),
    ],
    edges: [
      { source: "w1", target: "a1", type: "authored" },
      { source: "w2", target: "a1", type: "authored" },
      { source: "w3", target: "a2", type: "authored" },
    ],
  };

  it("只保留匹配阅读状态的作品及其作者,名下无匹配作品的作者一并隐藏", () => {
    const out = filterWorksByReading(readingData, "read");
    const ids = out.nodes.map((n) => n.id).sort();
    expect(ids).toEqual(["a1", "a2", "w1", "w3"]);
  });

  it("全部时原样返回", () => {
    expect(filterWorksByReading(readingData, "all")).toBe(readingData);
  });
});

describe("filterAuthorIslands", () => {
  const data = {
    nodes: [
      node("a1", "author"),
      node("w1", "work", { author_id: "a1" }), // 有 ECHO 提及关系
      node("w2", "work", { author_id: "a1" }), // 孤岛作品
      node("w3", "work", { author_id: "a2" }), // 有 ECHO 提及关系
    ],
    edges: [
      { source: "w1", target: "w3", type: "echo" },
      { source: "w1", target: "a1", type: "authored" },
      { source: "w2", target: "a1", type: "authored" },
    ],
  };

  it("隐藏无提及关系的孤岛作品,始终保留中心作者节点", () => {
    const out = filterAuthorIslands(data);
    expect(out.nodes.map((n) => n.id).sort()).toEqual(["a1", "w1", "w3"]);
    expect(out.edges.some((e) => e.source === "w1" && e.target === "a1")).toBe(true);
    expect(out.edges.some((e) => e.source === "w2" && e.target === "a1")).toBe(false);
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

describe("islandWorkCount", () => {
  it("统计没有 ECHO 提及关系的作品数", () => {
    const d = {
      nodes: [node("w1", "work"), node("w2", "work"), node("w3", "work"), node("a1", "author")],
      edges: [
        { source: "w1", target: "w2", type: "echo" },
        { source: "w1", target: "a1", type: "authored" },
      ],
    };
    expect(islandWorkCount(d)).toBe(1); // 只有 w3 无提及关系
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

describe("maxEchoHops", () => {
  it("从单个作品出发返回可达最远跳数(链 w1->w2->w3->w4)", () => {
    const d = {
      nodes: [node("w1", "work"), node("w2", "work"), node("w3", "work"), node("w4", "work")],
      edges: [
        { source: "w1", target: "w2", type: "echo" },
        { source: "w2", target: "w3", type: "echo" },
        { source: "w3", target: "w4", type: "echo" },
        { source: "w1", target: "a1", type: "authored" }, // 非 echo 边不参与
      ],
    };
    expect(maxEchoHops(d, ["w1"])).toBe(3);
    expect(maxEchoHops(d, ["w4"])).toBe(3);
    expect(maxEchoHops(d, ["w2"])).toBe(2);
  });

  it("多 seed 取并集的最远距离(作者名下多部作品)", () => {
    const d = {
      nodes: [node("w1", "work"), node("w2", "work"), node("w3", "work")],
      edges: [
        { source: "w1", target: "w2", type: "echo" },
        { source: "w2", target: "w3", type: "echo" },
      ],
    };
    expect(maxEchoHops(d, ["w1", "w2"])).toBe(1); // w3 距 seed 集合 1 跳
  });

  it("无边/孤立节点返回 0", () => {
    expect(maxEchoHops({ nodes: [node("x", "work")], edges: [] }, ["x"])).toBe(0);
  });
});
