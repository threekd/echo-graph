/* 管理令牌的存取与校验(Admin 组件与 App 初始化共用,避免重复代码)。 */

const TOKEN_KEY = "echo_graph_admin_token";

export function getAdminToken(): string {
  try { return sessionStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; }
}

export function setAdminToken(token: string): void {
  try { sessionStorage.setItem(TOKEN_KEY, token); } catch { /* ignore */ }
}

export function clearAdminToken(): void {
  try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
}

// 校验令牌:请求管理数据接口,2xx 视为有效(401/403/503 均无效)
export async function validateAdminToken(token: string): Promise<boolean> {
  try {
    const r = await fetch("/api/admin/data", {
      headers: { Authorization: "Bearer " + token },
    });
    return r.ok;
  } catch {
    return false;
  }
}
