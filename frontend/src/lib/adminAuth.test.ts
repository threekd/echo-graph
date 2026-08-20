import { afterEach, describe, expect, it, vi } from "vitest";
import { validateAdminToken } from "./adminAuth";

describe("validateAdminToken", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("带 Bearer 头请求管理接口,2xx 视为有效", async () => {
    const fn = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fn);
    await expect(validateAdminToken("secret")).resolves.toBe(true);
    expect(fn).toHaveBeenCalledWith("/api/admin/data", {
      headers: { Authorization: "Bearer secret" },
    });
  });

  it("401/403 等非 2xx 视为无效", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 401 }));
    await expect(validateAdminToken("bad")).resolves.toBe(false);
  });

  it("网络异常视为无效", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    await expect(validateAdminToken("secret")).resolves.toBe(false);
  });
});
