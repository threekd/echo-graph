/* 账号 API:注册 / 登录 / 登出 / 会话查询(httpOnly Cookie 由浏览器自动携带)。 */

export interface AuthUser {
  id: string;
  email: string;
  username?: string; // 唯一用户名(展示/跃迁标识)
  nickname?: string | null; // 昵称(展示用,优先于用户名)
  bio?: string | null; // 简介(长文本,可选)
  role: string;
  vip?: boolean; // VIP 标记(拥有 AI 书籍导入与本人 AI 草稿审核权限)
  space_visibility?: "public" | "private"; // 星云可见性(星际跃迁是否可访问)
  email_verified_at?: string | null; // 邮箱验证时间(未验证为 null;未开启验证为注册时间)
}

export interface AuthConfig {
  turnstileSiteKey: string;
  landingSpace?: string | null; // 游客落地星云用户名(.env LANDING_SPACE,可空)
}

export interface AuthResult {
  user: AuthUser | null;
  error: string;
  requiresVerification?: boolean; // 注册后需要先邮箱验证(未自动登录)
}

async function parseAuthResponse(r: Response): Promise<AuthResult> {
  let data: any = null;
  try {
    data = await r.json();
  } catch {
    /* 非 JSON 响应,保留 status 文案 */
  }
  if (r.ok) {
    return {
      user: (data && data.user) || null,
      error: "",
      requiresVerification: !!(data && data.requiresVerification),
    };
  }
  return { user: null, error: (data && data.detail) || "请求失败(" + r.status + ")" };
}

export async function fetchAuthConfig(): Promise<AuthConfig> {
  try {
    const r = await fetch("/api/auth/config");
    if (!r.ok) return { turnstileSiteKey: "", landingSpace: null };
    const d = await r.json();
    return {
      turnstileSiteKey: d.turnstileSiteKey || "",
      landingSpace: d.landingSpace || null,
    };
  } catch {
    return { turnstileSiteKey: "", landingSpace: null };
  }
}

export async function fetchMe(): Promise<AuthUser | null> {
  try {
    const r = await fetch("/api/auth/me");
    if (!r.ok) return null;
    const d = await r.json();
    return d.user || null;
  } catch {
    return null;
  }
}

export async function register(
  email: string,
  password: string,
  turnstileToken?: string,
  username?: string | null,
  nickname?: string | null
): Promise<AuthResult> {
  const r = await fetch("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email,
      password,
      turnstile: turnstileToken || null,
      username: username || null,
      nickname: nickname || null,
    }),
  });
  return parseAuthResponse(r);
}

export async function login(email: string, password: string): Promise<AuthResult> {
  const r = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  return parseAuthResponse(r);
}

export async function verifyEmail(token: string): Promise<AuthResult> {
  const r = await fetch("/api/auth/verify-email", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  return parseAuthResponse(r);
}

export async function resendVerification(email: string): Promise<AuthResult> {
  const r = await fetch("/api/auth/resend-verification", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  return parseAuthResponse(r);
}

export async function forgotPassword(email: string): Promise<AuthResult> {
  const r = await fetch("/api/auth/forgot-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  return parseAuthResponse(r);
}

export async function resetPassword(token: string, password: string): Promise<AuthResult> {
  const r = await fetch("/api/auth/reset-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, password }),
  });
  return parseAuthResponse(r);
}

export async function logout(): Promise<void> {
  try {
    await fetch("/api/auth/logout", { method: "POST" });
  } catch {
    /* 网络异常也照常清除本地登录态 */
  }
}

export interface ProfilePatch {
  nickname?: string | null;
  bio?: string | null;
  space_visibility?: "public" | "private";
}

export async function updateProfile(patch: ProfilePatch): Promise<AuthResult> {
  const r = await fetch("/api/auth/me", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return parseAuthResponse(r);
}

// 用户展示名:昵称 > 用户名 > 邮箱(邮箱仅兜底,不用于公开显示)
export function userDisplayName(user: AuthUser | null | undefined): string {
  if (!user) return "";
  return (user.nickname || "").trim() || (user.username || "").trim() || user.email;
}
