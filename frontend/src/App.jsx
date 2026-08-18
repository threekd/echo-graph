import React, { useEffect, useRef } from "react";
import { AppProvider, useApp } from "./store.jsx";
import GraphCanvas from "./components/GraphCanvas.jsx";
import Sidebar from "./components/Sidebar.jsx";
import Panel from "./components/Panel.jsx";
import Toast from "./components/Toast.jsx";
import Guide from "./components/Guide.jsx";
import Admin from "./components/Admin.jsx";
import { loadGraphData } from "./lib/api.js";
import { renderMain, setStateRef, selectNode, renderRipple, renderAuthorView, renderPath } from "./lib/graph.js";
import { setOnViewChange } from "./lib/renderer.js";

function AppContent() {
  const { state, dispatch } = useApp();
  const stateRef = useRef(null);
  stateRef.current = { state, dispatch };

  useEffect(() => {
    setStateRef(stateRef);
    setOnViewChange(({ kind }) => {
      dispatch({ type: "SET_VIEW", view: kind });
    });
    loadGraphData()
      .then((data) => {
        dispatch({ type: "SET_DATA", data });
        renderMain({}, data);
      })
      .catch((err) => {
        dispatch({ type: "SET_TOAST", msg: "加载图谱失败: " + err.message });
      });
  }, []);

  // 左右侧边栏边缘感应:鼠标靠近屏幕边缘时滑出
  useEffect(() => {
    let lastX = -1;
    const onMove = (e) => {
      const left = document.getElementById("sidebar-left");
      const right = document.getElementById("panel");
      if (left && e.clientX < 8) left.classList.add("show");
      if (right && e.clientX > window.innerWidth - 8) right.classList.add("show");
      lastX = e.clientX;
    };
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, []);

  // 节点点击 → 涟漪/作者视图
  useEffect(() => {
    // URL 深链处理:#v=main / #v=ripple:id:hops / #v=author:id / #v=path:from,to
    const handleHash = () => {
      const h = location.hash.replace(/^#/, "");
      if (!h) return;
      const parts = {};
      h.split("&").forEach((p) => {
        const kv = p.split("=");
        parts[kv[0]] = kv[1];
      });
      const v = parts.v || "";
      if (v.indexOf("ripple:") === 0) {
        const seg = v.slice(7).split(":");
        const id = seg[0];
        const hops = parseInt(seg[1], 10) || 1;
        const node = stateRef.current.state.fullData.nodes.find((n) => n.id === id);
        if (node) {
          if (node.type === "work") {
            fetch("/api/work/" + encodeURIComponent(id))
              .then((r) => r.json())
              .then((d) => {
                renderRipple(d);
                dispatch({ type: "SET_PANEL", panel: { type: "work", d } });
                dispatch({ type: "SET_EXPAND", value: hops });
                if (hops > 1) {
                  import("./lib/graph.js").then(({ expandRippleDebounced }) => expandRippleDebounced(hops));
                }
              });
          } else {
            renderAuthorView(node);
          }
        }
      } else if (v.indexOf("author:") === 0) {
        const id = v.slice(7);
        const node = stateRef.current.state.fullData.nodes.find((n) => n.id === id);
        if (node) renderAuthorView(node);
      } else if (v.indexOf("path:") === 0) {
        const seg = v.slice(5).split(",");
        renderPath(seg[0], seg[1]);
      }
    };
    window.addEventListener("hashchange", handleHash);
    handleHash();
    return () => window.removeEventListener("hashchange", handleHash);
  }, []);

  return (
    <div className="app-shell">
      <GraphCanvas />
      <Sidebar />
      <Panel />
      <Toast />
      <Guide />
      {state.adminOpen && <Admin />}
    </div>
  );
}

export default function App() {
  return (
    <AppProvider>
      <AppContent />
    </AppProvider>
  );
}
