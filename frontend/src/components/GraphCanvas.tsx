import { useEffect, useRef, type PointerEvent as ReactPointerEvent } from "react";
import { useApp } from "../store";
import { initThree, update as rendererUpdate, pickNode, setHoveredNode, disposeThree } from "../lib/renderer";
import { selectNode, showNodeDetail } from "../lib/graph";

export default function GraphCanvas() {
  const { state } = useApp();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const hoveredRef = useRef<string | null>(null);
  const pendingHover = useRef<string | null>(null); // 指针当前命中的节点(待停留确认)
  const hoverTimer = useRef<number | null>(null);
  const dragRef = useRef<{ down: boolean; moved: boolean; x: number; y: number }>({
    down: false,
    moved: false,
    x: 0,
    y: 0,
  });
  const rafRef = useRef<number>(0);
  const HOVER_DELAY_MS = 100; // 停留超过该时长才视为悬停(暂停旋转 + 显示详情)

  const cancelHoverTimer = () => {
    if (hoverTimer.current !== null) {
      window.clearTimeout(hoverTimer.current);
      hoverTimer.current = null;
    }
  };

  useEffect(() => {
    if (!containerRef.current) return;
    // 星空背景
    const starsWrap = document.createElement("div");
    starsWrap.id = "stars";
    for (let i = 0; i < 150; i++) {
      const s = document.createElement("div");
      s.className = "star";
      const size = (Math.random() * 1.7 + 0.6).toFixed(1);
      s.style.width = size + "px";
      s.style.height = size + "px";
      s.style.left = (Math.random() * 100).toFixed(2) + "%";
      s.style.top = (Math.random() * 100).toFixed(2) + "%";
      const hue = Math.random() < 0.72 ? "255,255,255" : (Math.random() < 0.5 ? "170,205,255" : "255,225,170");
      s.style.background = "rgba(" + hue + ",0.95)";
      s.style.boxShadow = "0 0 " + (Math.random() * 4 + 2).toFixed(1) + "px rgba(" + hue + ",0.8)";
      s.style.setProperty("--d", (Math.random() * 4 + 2.5).toFixed(1) + "s");
      s.style.setProperty("--delay", (Math.random() * 6).toFixed(1) + "s");
      starsWrap.appendChild(s);
    }
    containerRef.current.appendChild(starsWrap);

    initThree(containerRef.current);
    return () => {
      disposeThree();
      if (starsWrap.parentNode) starsWrap.parentNode.removeChild(starsWrap);
    };
  }, []);

  // 受控渲染:React 持有 viewData/currentView,数据变化时驱动渲染器执行绘制
  useEffect(() => {
    rendererUpdate(state.currentView, state.viewData);
  }, [state.currentView, state.viewData]);

  useEffect(() => {
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  // 节点点击/悬停由 React 事件委托:拾取与视觉状态经 renderer 的纯 API 完成
  const handlePointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (dragRef.current.down) {
      const d = dragRef.current;
      if (Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) > 4) d.moved = true;
      return;
    }
    if (rafRef.current) return; // rAF 节流,避免每像素触发
    const x = e.clientX;
    const y = e.clientY;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0;
      const id = pickNode(x, y);
      pendingHover.current = id;
      if (id === hoveredRef.current) return; // 已在悬停态,无需变化
      cancelHoverTimer();
      if (!id) {
        // 离开节点:立即清除悬停态
        hoveredRef.current = null;
        setHoveredNode(null);
        return;
      }
      // 短暂经过不触发;停留 HOVER_DELAY_MS 后,暂停旋转与显示详情同时生效
      hoverTimer.current = window.setTimeout(() => {
        hoverTimer.current = null;
        if (pendingHover.current === id) {
          hoveredRef.current = id;
          setHoveredNode(id);
          showNodeDetail(id);
        }
      }, HOVER_DELAY_MS);
    });
  };

  const handlePointerLeave = () => {
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current); // 取消排队的拾取,避免离开画布后悬停残留
      rafRef.current = 0;
    }
    cancelHoverTimer();
    pendingHover.current = null;
    if (hoveredRef.current) {
      hoveredRef.current = null;
      setHoveredNode(null);
    }
  };

  const handlePointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    dragRef.current = { down: true, moved: false, x: e.clientX, y: e.clientY };
  };

  const handlePointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    const wasClick = dragRef.current.down && !dragRef.current.moved;
    dragRef.current = { down: false, moved: false, x: 0, y: 0 };
    if (wasClick && e.button === 0) {
      const id = pickNode(e.clientX, e.clientY);
      if (id) selectNode(id);
    }
  };


  return (
    <div
      id="graph"
      ref={containerRef}
      onPointerMove={handlePointerMove}
      onPointerDown={handlePointerDown}
      onPointerUp={handlePointerUp}
      onPointerLeave={handlePointerLeave}
    ></div>
  );
}
