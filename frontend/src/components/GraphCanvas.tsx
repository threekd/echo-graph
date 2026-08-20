import { useEffect, useRef, type PointerEvent as ReactPointerEvent } from "react";
import { useApp } from "../store";
import { initThree, update as rendererUpdate, pickNode, setHoveredNode, disposeThree } from "../lib/renderer";
import { selectNode, showNodeDetail } from "../lib/graph";

export default function GraphCanvas() {
  const { state } = useApp();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const hoveredRef = useRef<string | null>(null); // 已确认的悬停节点
  const pendingHover = useRef<string | null>(null); // 悬停候选(进入节点即锁定)
  const hoverEnterPos = useRef<{ x: number; y: number } | null>(null);
  const hoverTimer = useRef<number | null>(null);
  const dragRef = useRef<{ down: boolean; moved: boolean; x: number; y: number }>({
    down: false,
    moved: false,
    x: 0,
    y: 0,
  });
  const rafRef = useRef<number>(0);
  const HOVER_DELAY_MS = 300; // 停住约 0.3 秒后暂停旋转并显示详情
  const HOVER_RELEASE_PX = 30; // 移出该距离视为离开节点(容忍旋转漂移与微抖)

  const cancelHoverTimer = () => {
    if (hoverTimer.current !== null) {
      window.clearTimeout(hoverTimer.current);
      hoverTimer.current = null;
    }
  };

  const releaseHover = () => {
    pendingHover.current = null;
    hoverEnterPos.current = null;
    cancelHoverTimer();
    if (hoveredRef.current) {
      hoveredRef.current = null;
      setHoveredNode(null);
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
      if (id) {
        if (id !== pendingHover.current) {
          // 命中新节点:结束旧悬停,锁定新候选并开始 0.3s 计时
          if (hoveredRef.current && hoveredRef.current !== id) {
            hoveredRef.current = null;
            setHoveredNode(null);
          }
          pendingHover.current = id;
          hoverEnterPos.current = { x, y };
          cancelHoverTimer();
          hoverTimer.current = window.setTimeout(() => {
            hoverTimer.current = null;
            if (pendingHover.current === id) {
              hoveredRef.current = id;
              setHoveredNode(id);
              showNodeDetail(id);
            }
          }, HOVER_DELAY_MS);
        }
        return;
      }
      // 未命中节点:离上次进入点足够远才释放候选(容忍漂移与微抖),避免悬停难以触发
      const pos = hoverEnterPos.current;
      if (pendingHover.current && pos) {
        if (Math.hypot(x - pos.x, y - pos.y) > HOVER_RELEASE_PX) releaseHover();
      }
    });
  };

  const handlePointerLeave = () => {
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current); // 取消排队的拾取,避免离开画布后悬停残留
      rafRef.current = 0;
    }
    releaseHover();
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
