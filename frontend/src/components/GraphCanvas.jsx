import React, { useEffect, useRef } from "react";
import { initThree, setOnNodeClick, setOnNodeHover } from "../lib/renderer.js";
import { selectNode, showNodeDetail } from "../lib/graph.js";

export default function GraphCanvas() {
  const containerRef = useRef(null);

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
    setOnNodeClick(selectNode);
    setOnNodeHover(showNodeDetail);
  }, []);

  return <div id="graph" ref={containerRef}></div>;
}
