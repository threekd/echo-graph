/* 通用工具与常量 */

export function el(id) {
  return document.getElementById(id);
}

export function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

export const MENTION_COLOR = 0x67e8f9; // 提及(ECHO)连线:青色星光
