import React, { useEffect, useRef } from "react";
import { AppProvider, useApp } from "./store.jsx";
import GraphCanvas from "./components/GraphCanvas.jsx";
import Sidebar from "./components/Sidebar.jsx";
import Panel from "./components/Panel.jsx";
import Toast from "./components/Toast.jsx";
import Guide from "./components/Guide.jsx";
import Admin from "./components/Admin.jsx";
import { loadGraphData, workDetail } from "./lib/api.js";
import {
  renderMain, setStateRef, selectNode, renderRipple, renderAuthorView, renderPath, expandRippleDebounced,
  isSelfWrittenHash,
} from "./lib/graph.js";
import { setOnViewChange } from "./lib/renderer.js";

function parseCam(s) {
  const parts = String(s || "").split(",").map((x) => parseFloat(x));
  if (parts.length < 6 || parts.some((x) => isNaN(x))) return null;
  return { theta: parts[0], phi: parts[1], radius: parts[2], cx: parts[3], cy: parts[4], cz: parts[5] };
}

function AppContent() {
  const { state, dispatch } = useApp();
  const stateRef = useRef(null);
  stateRef.current = { state, dispatch };

  // URL 深链处理:#v=main / #v=ripple:id:hops / #v=author:id / #v=path:from,to
  // cam / islands / authors 参数用于恢复分享链接;数据加载完成后再次应用,保证首载深链生效
  const applyHash = (data) => {
    const st = data ? { fullData: data } : stateRef.current.state;
    if (!st.fullData || !st.fullData.nodes.length) return;
    if (isSelfWrittenHash()) return; // 自身写入的 hash,避免重复渲染
    const h = location.hash.replace(/^#/, "");
    if (!h) return;
    const parts = {};
    h.split("&").forEach((p) => {
      const kv = p.split("=");
      parts[kv[0]] = kv[1] == null ? "" : decodeURIComponent(kv[1]);
    });
    const v = parts.v || "";
    const cam = parts.cam ? parseCam(parts.cam) : null;
    const hideIslands = parts.islands === "1" || location.search.indexOf("hideislands") !== -1;
    const showAuthors = parts.authors !== "0";
    if (v.indexOf("ripple:") === 0) {
      const seg = v.slice(7).split(":");
      const id = seg[0];
      const hops = parseInt(seg[1], 10) || 1;
      const node = st.fullData.nodes.find((n) => n.id === id);
      if (node) {
        if (node.type === "work") {
          workDetail(id).then((d) => {
            renderRipple(d, hops);
            dispatch({ type: "SET_PANEL", panel: { type: "work", d } });
            if (hops > 1) expandRippleDebounced(hops);
          });
        } else {
          renderAuthorView(node);
        }
      }
    } else if (v.indexOf("author:") === 0) {
      const id = v.slice(7);
      const node = st.fullData.nodes.find((n) => n.id === id);
      if (node) renderAuthorView(node);
    } else if (v.indexOf("path:") === 0) {
      const seg = v.slice(5).split(",");
      renderPath(seg[0], seg[1]);
    } else if (v === "main" || cam || hideIslands || !showAuthors) {
      renderMain(cam ? { camera: cam } : {}, st.fullData, { hideIslands, showAuthors });
    }
  };

  useEffect(() => {
    setStateRef(stateRef);
    setOnViewChange(({ kind }) => {
      dispatch({ type: "SET_VIEW", view: kind });
    });
    loadGraphData()
      .then((data) => {
        dispatch({ type: "SET_DATA", data });
        if (location.hash.replace(/^#/, "")) {
          applyHash(data);
        } else {
          renderMain({}, data);
        }
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

  // 浏览器前进/后退或手动修改 hash 时导航
  useEffect(() => {
    window.addEventListener("hashchange", applyHash);
    return () => window.removeEventListener("hashchange", applyHash);
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
