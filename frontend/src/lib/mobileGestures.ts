/* 移动端手势:底部左侧上划呼出功能栏,底部右侧上划呼出详情栏;点击栏外收起。
 *
 * 打开手势仅在没有任何栏打开时生效(两栏天然互斥,不会同时出现);
 * 限定屏幕底部区域,避免与图谱单指平移/双指操作冲突。
 */

import { useEffect } from "react";

const MOBILE_QUERY = "(max-width: 768px)";
const SWIPE_THRESHOLD = 50;
const BOTTOM_ZONE = 140; // 底部手势区高度(上划打开功能栏/详情栏)

export function isMobileLayout(): boolean {
  // 非浏览器环境(单测/SSR)没有 matchMedia,按桌面处理
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(MOBILE_QUERY).matches
    : false;
}

interface SwipeState {
  startX: number;
  startY: number;
  opened: boolean; // 本次手势已触发上划
}

// 底部手势区触摸标记:渲染器据此抑制该区域"纵向向上"的单指平移,
// 避免"呼出栏的同时页面跟着平移";横向平移、双指旋转/缩放不受影响
let bottomGestureTouch = false;

export function isBottomGestureTouch(): boolean {
  return bottomGestureTouch;
}

export function useMobileGestures(): void {
  useEffect(() => {
    if (!isMobileLayout()) return;

    const sidebar = () => document.getElementById("sidebar-left");
    const panel = () => document.getElementById("panel");
    const isOpen = (el: HTMLElement | null) => !!el && el.classList.contains("show");
    const inside = (el: HTMLElement | null, target: EventTarget | null) =>
      !!el && target instanceof Node && el.contains(target);
    const closeAll = () => {
      sidebar()?.classList.remove("show");
      panel()?.classList.remove("show");
    };

    let st: SwipeState | null = null;

    const onTouchStart = (e: TouchEvent) => {
      st =
        e.touches.length === 1
          ? {
              startX: e.touches[0].clientX,
              startY: e.touches[0].clientY,
              opened: false,
            }
          : null;
      bottomGestureTouch = !!st && st.startY >= window.innerHeight - BOTTOM_ZONE;
    };

    const onTouchMove = (e: TouchEvent) => {
      if (!st || e.touches.length !== 1) return;
      const t = e.touches[0];
      const dx = t.clientX - st.startX;
      const dy = t.clientY - st.startY;
      const vertical = Math.abs(dy) > Math.abs(dx) * 1.2;
      const s = sidebar();
      const p = panel();

      if (
        !st.opened &&
        vertical &&
        dy < -SWIPE_THRESHOLD &&
        st.startY >= window.innerHeight - BOTTOM_ZONE &&
        !isOpen(s) &&
        !isOpen(p)
      ) {
        if (st.startX < window.innerWidth / 2) {
          s?.classList.add("show"); // 底部左侧上划 → 功能栏
        } else {
          p?.classList.add("show"); // 底部右侧上划 → 详情栏
        }
        st.opened = true;
      }
    };

    const onTouchEnd = (e: TouchEvent) => {
      bottomGestureTouch = false;
      if (!st || !e.changedTouches[0]) return;
      const t = e.changedTouches[0];
      const dist = Math.hypot(t.clientX - st.startX, t.clientY - st.startY);
      const s = sidebar();
      const p = panel();
      if (dist < 12 && (isOpen(s) || isOpen(p))) {
        const target = e.target;
        if (!inside(s, target) && !inside(p, target)) closeAll();
      }
      st = null;
    };

    const onTouchCancel = () => {
      bottomGestureTouch = false;
      st = null;
    };

    window.addEventListener("touchstart", onTouchStart, { passive: true });
    window.addEventListener("touchmove", onTouchMove, { passive: true });
    window.addEventListener("touchend", onTouchEnd, { passive: true });
    window.addEventListener("touchcancel", onTouchCancel, { passive: true });
    return () => {
      window.removeEventListener("touchstart", onTouchStart);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("touchend", onTouchEnd);
      window.removeEventListener("touchcancel", onTouchCancel);
    };
  }, []);
}
