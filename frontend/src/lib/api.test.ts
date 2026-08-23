import { describe, expect, it } from "vitest";
import { apiRoot, spaceFromParam, spaceParamFromState, spaceUserId } from "./api";

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
