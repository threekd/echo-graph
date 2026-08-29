import { beforeAll, describe, expect, it } from "vitest";
import { authorViewData, renderAuthorView, renderRipple, resolveViewCamera, setStateRef } from "./graph";
import { initialState } from "../store";

beforeAll(() => {
  (globalThis as any).location = {
    hash: "",
    replace: (h: string) => { (globalThis as any).location.hash = h; },
  };
});

function withEmptyState() {
  const dispatched: any[] = [];
  // 模拟首载深链:dispatch(SET_DATA) 尚未刷新,getState().fullData 仍是空图
  setStateRef({ current: { state: { ...initialState, fullData: { nodes: [], edges: [] } }, dispatch: (a: any) => dispatched.push(a) } });
  return dispatched;
}

const mainDefault = { theta: -Math.PI / 2 + 0.4, phi: Math.PI / 2 - 0.18, radius: 1500, cx: 0, cy: 0, cz: 0 };

describe("resolveViewCamera", () => {
  it("无 opts 时返回各视图默认相机", () => {
    expect(resolveViewCamera("main", {})).toEqual(mainDefault);
    expect(resolveViewCamera("ripple", {})?.radius).toBe(1150);
    expect(resolveViewCamera("author", {})?.radius).toBe(1200);
    expect(resolveViewCamera("path", {})?.radius).toBe(1250);
  });

  it("preserveCamera 时不改相机(返回 undefined)", () => {
    expect(resolveViewCamera("ripple", { preserveCamera: true })).toBeUndefined();
  });

  it("显式 camera 优先于默认相机(深链恢复)", () => {
    const cam = { theta: 1, phi: 2, radius: 3, cx: 4, cy: 5, cz: 6 };
    expect(resolveViewCamera("main", { camera: cam })).toEqual(cam);
    expect(resolveViewCamera("ripple", { preserveCamera: true, camera: cam })).toEqual(cam);
  });

  it("未知视图无默认相机", () => {
    expect(resolveViewCamera("unknown", {})).toBeUndefined();
  });
});

describe("authorViewData", () => {
  const author = { id: "a1", type: "author", label: "A" };
  const fullData: any = {
    nodes: [
      author,
      { id: "w1", type: "work", label: "W1", author_id: "a1" },
      { id: "w2", type: "work", label: "W2", author_id: "a1" },
      { id: "w3", type: "work", label: "W3", author_id: "a2" },
      { id: "w4", type: "work", label: "W4", author_id: "a2" },
    ],
    edges: [
      { source: "w1", target: "w3", type: "echo" },
      { source: "w3", target: "w4", type: "echo" },
    ],
  };

  it("层级 1 仅显示作者与其名下作品", () => {
    const data = authorViewData(author, 1, fullData);
    expect(data.nodes.map((n) => n.id).sort()).toEqual(["a1", "w1", "w2"]);
    expect(data.edges.every((e) => e.type === "authored")).toBe(true);
  });

  it("层级 2 向外扩 1 跳(纳入 w3)", () => {
    const data = authorViewData(author, 2, fullData);
    expect(data.nodes.map((n) => n.id).sort()).toEqual(["a1", "w1", "w2", "w3"]);
    expect(data.edges.some((e) => e.source === "w1" && e.target === "w3")).toBe(true);
  });

  it("层级 3 继续扩到 w4", () => {
    const data = authorViewData(author, 3, fullData);
    expect(data.nodes.map((n) => n.id).sort()).toEqual(["a1", "w1", "w2", "w3", "w4"]);
  });

  it("扩散到的作品的相关作者也加入视图(含 authored 边)", () => {
    const withAuthor: any = {
      nodes: [
        author,
        { id: "a2", type: "author", label: "B" },
        { id: "w1", type: "work", label: "W1", author_id: "a1" },
        { id: "w3", type: "work", label: "W3", author_id: "a2" },
      ],
      edges: [{ source: "w1", target: "w3", type: "echo" }],
    };
    const data = authorViewData(author, 2, withAuthor);
    expect(data.nodes.map((n) => n.id).sort()).toEqual(["a1", "a2", "w1", "w3"]);
    expect(data.edges).toContainEqual({ source: "w3", target: "a2", type: "authored" });
  });

  it("包含合著作品(author_ids 数组)", () => {
    const coAuthor = { id: "a2", type: "author", label: "B" };
    const full: any = {
      nodes: [
        { id: "a1", type: "author", label: "A" },
        coAuthor,
        { id: "w1", type: "work", label: "W1", author_ids: ["a1"] },
        { id: "w2", type: "work", label: "W2", author_ids: ["a1", "a2"] },
      ],
      edges: [],
    };
    const data = authorViewData(coAuthor, 1, full);
    expect(data.nodes.map((n) => n.id).sort()).toEqual(["a1", "a2", "w2"]);
    expect(data.edges).toEqual([
      { source: "w2", target: "a1", type: "authored" },
      { source: "w2", target: "a2", type: "authored" },
    ]);
  });
});

describe("首载深链渲染(显式 fullData)", () => {
  it("renderAuthorView 在 state 未刷新时也能渲染作者与作品", () => {
    const author = { id: "a1", type: "author", label: "A" };
    const fullData: any = {
      nodes: [
        author,
        { id: "w1", type: "work", label: "W1", author_id: "a1" },
        { id: "w2", type: "work", label: "W2", author_id: "a2" },
      ],
      edges: [{ source: "w1", target: "w2", type: "echo" }],
    };
    const dispatched = withEmptyState();
    renderAuthorView(author, { hops: 1, fullData });
    const data = dispatched.find((a) => a.type === "SET_VIEW_DATA")?.data;
    expect(data.nodes.map((n: any) => n.id).sort()).toEqual(["a1", "w1"]);
  });

  it("showAuthors=false 时隐藏相关作者但保留中心作者锚点", () => {
    const author = { id: "a1", type: "author", label: "A" };
    const fullData: any = {
      nodes: [
        author,
        { id: "a2", type: "author", label: "B" },
        { id: "w1", type: "work", label: "W1", author_id: "a1" },
        { id: "w3", type: "work", label: "W3", author_id: "a2" },
      ],
      edges: [{ source: "w1", target: "w3", type: "echo" }],
    };
    const dispatched = withEmptyState();
    renderAuthorView(author, { hops: 2, fullData, showAuthors: false });
    const data = dispatched.find((a) => a.type === "SET_VIEW_DATA")?.data;
    const ids = (data.nodes as any[]).map((n) => n.id).sort();
    expect(ids).toEqual(["a1", "w1", "w3"]); // 中心作者保留
    expect(ids).not.toContain("a2");
    expect(data.edges).toContainEqual({ source: "w1", target: "a1", type: "authored" });
    expect(data.edges).toContainEqual({ source: "w1", target: "w3", type: "echo" });
    expect((data.edges as any[]).some((e) => e.type === "authored" && e.target === "a2")).toBe(false);
  });

  it("renderRipple 在 state 未刷新时也能渲染中心与邻居作品", () => {
    const fullData: any = {
      nodes: [
        { id: "c", type: "work", label: "C", author_id: "a1" },
        { id: "n1", type: "work", label: "N1", author_id: "a2" },
      ],
      edges: [],
    };
    const dispatched = withEmptyState();
    const detail: any = { work: { id: "c" }, mentioned_by: [{ source: "n1", evidence: "x" }], mentions: [] };
    renderRipple(detail, 1, { fullData });
    const data = dispatched.find((a) => a.type === "SET_VIEW_DATA")?.data;
    expect(data.nodes.map((n: any) => n.id).sort()).toEqual(["c", "n1"]);
  });

  it("renderRipple 为合著作品加入全部作者节点与归属边", () => {
    const fullData: any = {
      nodes: [
        { id: "a1", type: "author", label: "A" },
        { id: "a2", type: "author", label: "B" },
        { id: "c", type: "work", label: "C", author_ids: ["a1", "a2"] },
        { id: "n1", type: "work", label: "N1", author_ids: ["a1"] },
      ],
      edges: [],
    };
    const dispatched = withEmptyState();
    const detail: any = { work: { id: "c" }, mentioned_by: [{ source: "n1", evidence: "x" }], mentions: [] };
    renderRipple(detail, 1, { fullData });
    const data = dispatched.find((a) => a.type === "SET_VIEW_DATA")?.data;
    expect(data.nodes.filter((n: any) => n.type === "author").map((n: any) => n.id).sort())
      .toEqual(["a1", "a2"]);
    const authored = data.edges.filter((e: any) => e.type === "authored");
    expect(authored.map((e: any) => `${e.source}->${e.target}`).sort())
      .toEqual(["c->a1", "c->a2", "n1->a1"]);
  });
});
