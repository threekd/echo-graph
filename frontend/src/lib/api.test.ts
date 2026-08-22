import { describe, expect, it } from "vitest";
import { apiRoot, spaceUserId } from "./api";

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
});
