import { useCallback, useEffect, useRef } from "react";
import {
  AppProvider,
  useApp,
  type AppAction,
  type AppState,
  type CameraState,
  type GraphData,
} from "./store";
import GraphCanvas from "./components/GraphCanvas";
import Sidebar from "./components/Sidebar";
import Panel from "./components/Panel";
import Toast from "./components/Toast";
import Guide from "./components/Guide";
import Admin from "./components/Admin";
import { loadGraphData, loadStats, workDetail } from "./lib/api";
import {
  renderMain, setStateRef, renderRipple, renderAuthorView, renderPath, expandRippleDebounced,
  isSelfWrittenHash,
} from "./lib/graph";
import { setOnCameraChange } from "./lib/renderer";

function parseCam(s: string): CameraState | null {
  const parts = String(s || "").split(",").map((x) => parseFloat(x));
  if (parts.length < 6 || parts.some((x) => isNaN(x))) return null;
  return { theta: parts[0], phi: parts[1], radius: parts[2], cx: parts[3], cy: parts[4], cz: parts[5] };
}

function AppContent() {
  const { state, dispatch } = useApp();
  const stateRef = useRef<{ state: AppState; dispatch: (a: AppAction) => void } | null>(null);
  stateRef.current = { state, dispatch };

  // URL 深链处理:#v=main / #v=ripple:id:hops / #v=author:id / #v=path:from,to
  // cam / islands / authors 参数用于恢复分享链接;数据加载完成后再次应用,保证首载深链生效
  const applyHash = useCallback((data?: GraphData) => {
    if (isSelfWrittenHash()) return; // 自身写入的 hash,避免重复渲染
    const h = location.hash.replace(/^#/, "");
    if (!h) return;
    const fullData = data || stateRef.current!.state.fullData;
    if (!fullData || !fullData.nodes.length) return;
    const parts: Record<string, string> = {};
    h.split("&").forEach((p) => {
      const kv = p.split("=");
      parts[kv[0]] = kv[1] == null ? "" : decodeURIComponent(kv[1]);
    });
    const v = parts.v || "";
    const cam = parts.cam ? parseCam(parts.cam) : null;
    const flags = {
      hideIslands: parts.islands === "1" || location.search.indexOf("hideislands") !== -1,
      showAuthors: parts.authors !== "0",
    };
    const st = stateRef.current!.state;
    // 同步过滤状态到 React store(渲染函数同时接收显式 flags,不依赖同步生效)
    if (st.hideIslands !== flags.hideIslands || st.showAuthors !== flags.showAuthors) {
      dispatch({ type: "SET_HIDE_ISLANDS", value: flags.hideIslands });
      dispatch({ type: "SET_SHOW_AUTHORS", value: flags.showAuthors });
    }
    if (v.indexOf("ripple:") === 0) {
      const seg = v.slice(7).split(":");
      const id = seg[0];
      const hops = parseInt(seg[1], 10) || 1;
      const node = fullData.nodes.find((n) => n.id === id);
      if (node) {
        if (node.type === "work") {
          workDetail(id).then((d) => {
            renderRipple(d, hops, flags);
            dispatch({ type: "SET_PANEL", panel: { type: "work", d } });
            if (hops > 1) expandRippleDebounced(hops);
          }).catch(() => dispatch({ type: "SET_TOAST", msg: "加载作品详情失败" }));
        } else {
          renderAuthorView(node, flags);
        }
      }
    } else if (v.indexOf("author:") === 0) {
      const id = v.slice(7);
      const node = fullData.nodes.find((n) => n.id === id);
      if (node) renderAuthorView(node, flags);
    } else if (v.indexOf("path:") === 0) {
      const seg = v.slice(5).split(",");
      renderPath(seg[0], seg[1], flags);
    } else if (v === "main" || cam || flags.hideIslands || !flags.showAuthors) {
      renderMain(cam ? { camera: cam } : {}, fullData, flags);
    }
  }, [dispatch]);

  useEffect(() => {
    setStateRef(stateRef);
    setOnCameraChange((camera) => {
      dispatch({ type: "SET_CAMERA", camera });
    });
    Promise.all([loadGraphData(), loadStats()])
      .then(([data, stats]) => {
        dispatch({ type: "SET_DATA", data });
        dispatch({ type: "SET_STORE", name: (stats && stats.store) || "" });
        if (location.hash.replace(/^#/, "")) {
          applyHash(data);
        } else {
          renderMain({}, data);
        }
      })
      .catch((err) => {
        dispatch({ type: "SET_TOAST", msg: "加载图谱失败: " + err.message });
      });
  }, [applyHash, dispatch]);

  // 左右侧边栏边缘感应:鼠标靠近屏幕边缘时滑出
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const left = document.getElementById("sidebar-left");
      const right = document.getElementById("panel");
      if (left && e.clientX < 8) left.classList.add("show");
      if (right && e.clientX > window.innerWidth - 8) right.classList.add("show");
    };
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, []);

  // 浏览器前进/后退或手动修改 hash 时导航
  useEffect(() => {
    const onHashChange = () => applyHash();
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [applyHash]);

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
