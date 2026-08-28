import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchMe, forgotPassword, login, register, resetPassword, resendVerification, verifyEmail,
} from "./auth";

function fakeResponse(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

describe("auth API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetchMe 未登录返回 null", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse(401, { detail: "未登录" })));
    await expect(fetchMe()).resolves.toBeNull();
  });

  it("fetchMe 登录态返回用户", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        fakeResponse(200, { user: { id: "u1", email: "a@b.com", role: "user" } })
      )
    );
    await expect(fetchMe()).resolves.toEqual({ id: "u1", email: "a@b.com", role: "user" });
  });

  it("login 成功返回用户并携带 JSON 载荷", async () => {
    const fn = vi.fn().mockResolvedValue(
      fakeResponse(200, { user: { id: "u1", email: "a@b.com", role: "user" } })
    );
    vi.stubGlobal("fetch", fn);
    const r = await login("a@b.com", "password123");
    expect(r.user?.email).toBe("a@b.com");
    expect(fn).toHaveBeenCalledWith(
      "/api/auth/login",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ email: "a@b.com", password: "password123" }),
      })
    );
  });

  it("register 失败透出后端 detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(fakeResponse(400, { detail: "该邮箱已注册,请直接登录" }))
    );
    const r = await register("a@b.com", "password123", "turnstile-token");
    expect(r.user).toBeNull();
    expect(r.error).toBe("该邮箱已注册,请直接登录");
  });

  it("register 返回 requiresVerification(邮箱验证开启时)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        fakeResponse(200, { user: null, requiresVerification: true })
      )
    );
    const r = await register("a@b.com", "password123", "turnstile-token", "starlit");
    expect(r.requiresVerification).toBe(true);
  });

  it("verifyEmail 携带令牌并透出成功用户", async () => {
    const fn = vi.fn().mockResolvedValue(
      fakeResponse(200, { user: { id: "u1", email: "a@b.com", role: "user" } })
    );
    vi.stubGlobal("fetch", fn);
    const r = await verifyEmail("tok-123");
    expect(r.user?.id).toBe("u1");
    expect(fn).toHaveBeenCalledWith(
      "/api/auth/verify-email",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ token: "tok-123" }),
      })
    );
  });

  it("forgotPassword 提交邮箱", async () => {
    const fn = vi.fn().mockResolvedValue(fakeResponse(200, { ok: true }));
    vi.stubGlobal("fetch", fn);
    await forgotPassword("a@b.com");
    expect(fn).toHaveBeenCalledWith(
      "/api/auth/forgot-password",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ email: "a@b.com" }),
      })
    );
  });

  it("resetPassword 提交令牌与新密码", async () => {
    const fn = vi.fn().mockResolvedValue(fakeResponse(200, { ok: true }));
    vi.stubGlobal("fetch", fn);
    await resetPassword("tok-456", "new-pass-123");
    expect(fn).toHaveBeenCalledWith(
      "/api/auth/reset-password",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ token: "tok-456", password: "new-pass-123" }),
      })
    );
  });

  it("resendVerification 提交邮箱", async () => {
    const fn = vi.fn().mockResolvedValue(fakeResponse(200, { ok: true }));
    vi.stubGlobal("fetch", fn);
    await resendVerification("a@b.com");
    expect(fn).toHaveBeenCalledWith(
      "/api/auth/resend-verification",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ email: "a@b.com" }),
      })
    );
  });
});
