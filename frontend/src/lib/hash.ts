// URL hash 解析工具:深链视图参数 / 旧版分享链接(cam / islands / authors) / space 上下文
import type { CameraState } from "../store";

// cam=theta,phi,radius,cx,cy,cz(旧版分享链接的相机快照;缺位/非法返回 null)
export function parseCam(s: string): CameraState | null {
  const parts = String(s || "").split(",").map((x) => parseFloat(x));
  if (parts.length < 6 || parts.some((x) => isNaN(x))) return null;
  return { theta: parts[0], phi: parts[1], radius: parts[2], cx: parts[3], cy: parts[4], cz: parts[5] };
}

// 将 hash 解析为键值对(#v=main&space=mine&islands=1 → { v, space, islands })
export function parseHashParams(hash: string): Record<string, string> {
  const parts: Record<string, string> = {};
  const h = hash.replace(/^#/, "");
  if (!h) return parts;
  h.split("&").forEach((p) => {
    const kv = p.split("=");
    parts[kv[0]] = kv[1] == null ? "" : decodeURIComponent(kv[1]);
  });
  return parts;
}
