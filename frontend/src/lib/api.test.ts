import { afterEach, describe, expect, it, vi } from "vitest";
import {
  apiRoot, findPath, loadGraphData, search, spaceFromParam, spaceParamFromState, spaceUserId,
} from "./api";

function mockFetch(ok: boolean, body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok,
      status,
      json: async () => body,
    }))
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("space API routing", () => {
  it("routes public / mine / user space to the right prefix", () => {
    expect(apiRoot("public")).toBe("/api");
    expect(apiRoot("mine")).toBe("/api/me");
    expect(apiRoot("space:01a0-0000-0000-0001")).toBe("/api/space/01a0-0000-0000-0001");
  });

  it("extracts the user id from the space context", () => {
    expect(spaceUserId("space:u1")).toBe("u1");
    expect(spaceUserId("public")).toBeNull();
    expect(spaceUserId("mine")).toBeNull();
  });

  it("converts space state <-> url param", () => {
    expect(spaceParamFromState("public")).toBe("public");
    expect(spaceParamFromState("mine")).toBe("mine");
    expect(spaceParamFromState("space:u1")).toBe("u1");
    expect(spaceFromParam("public")).toBe("public");
    expect(spaceFromParam("mine")).toBe("mine");
    expect(spaceFromParam("01a02c3d-5ff8-74bf-9f75-6119c5efd6b1"))
      .toBe("space:01a02c3d-5ff8-74bf-9f75-6119c5efd6b1");
    expect(spaceFromParam("")).toBeNull();
    expect(spaceFromParam("bogus")).toBeNull();
    expect(spaceFromParam(undefined)).toBeNull();
  });
});

describe("getJson HTTP error handling", () => {
  it("resolves successful responses", async () => {
    mockFetch(true, { nodes: [], edges: [] });
    await expect(loadGraphData("public")).resolves.toEqual({ nodes: [], edges: [] });
  });

  it("throws with backend detail on 404", async () => {
    mockFetch(false, { detail: "work not found: abc" }, 404);
    await expect(loadGraphData("public")).rejects.toThrow("work not found: abc");
  });

  it("throws with generic status message on non-JSON errors", async () => {
    mockFetch(false, "boom", 500);
    await expect(search("q")).rejects.toThrow("请求失败(500)");
  });

  it("throws on findPath errors instead of resolving an error payload", async () => {
    mockFetch(false, { detail: "no mention path found" }, 404);
    await expect(findPath("a", "b")).rejects.toThrow("no mention path found");
  });
});
