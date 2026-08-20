import { Component, lazy, Suspense, useCallback, useEffect, useRef, type ReactNode } from "react";
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
import { loadGraphData, loadStats, workDetail } from "./lib/api";
import { clearAdminToken, getAdminToken, validateAdminToken } from "./lib/adminAuth";
import { isMobileLayout, useMobileGestures } from "./lib/mobileGestures";
import {
  renderMain, setStateRef, renderRipple, renderAuthorView, renderPath, expandRippleDebounced,
  isSelfWrittenHash,
} from "./lib/graph";
import { setOnCameraChange } from "./lib/renderer";

// 管理页与贡献弹窗按需加载(普通用户默认不可见,不打进首屏包)
const Admin = lazy(() => import("./components/Admin"));
const Contribute = lazy(() => import("./components/Contribute"));

// 懒加载 chunk 渲染异常时降级为空,避免整页白屏(图谱仍可用)
class ChunkBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.error("按需加载模块渲染失败:", error);
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}

function parseCam(s: string): CameraState | null {
  const parts = String(s || "").split(",").map((x) => parseFloat(x));
  if (parts.length < 6 || parts.some((x) => isNaN(x))) return null;
  return { theta: parts[0], phi: parts[1], radius: parts[2], cx: parts[3], cy: parts[4], cz: parts[5] };
}

function AppContent() {
  const { state, dispatch } = useApp();
  const stateRef = useRef<{ state: AppState; dispatch: (a: AppAction) => void } | null>(null);
  stateRef.current = { state, dispatch };
  useMobileGestures();
  // 同一 hash 在短时间内(hashchange/popstate/focus 多事件)只处理一次
  const lastAppliedHash = useRef<string | null>(null);
  const lastAppliedAt = useRef(0);

  // URL 深链处理:#v=main / #v=ripple:id:hops / #v=author:id / #v=path:from,to
  // cam / islands / authors 参数用于恢复旧版分享链接;数据加载完成后再次应用,保证首载深链生效
  const applyHash = useCallback((data?: GraphData) => {
    const current = location.hash;
    if (
      !data &&
      lastAppliedHash.current === current &&
      lastAppliedAt.current > 0 &&
      Date.now() - lastAppliedAt.current < 500
    ) {
      return;
    }
    lastAppliedHash.current = current;
    lastAppliedAt.current = Date.now();
    if (isSelfWrittenHash()) return; // 自身写入的 hash,避免重复渲染
    // #v=admin 或 hash 中含 admin(如用户把 ?admin 误加到 # 之后形成 "#v=main?admin")都视为管理入口;
    // "admin" 不可能出现在 UUID/视图参数中,判定安全
    if (location.hash.indexOf("admin") !== -1) {
      dispatch({ type: "SET_ADMIN", open: true });
      return;
    }
    const h = location.hash.replace(/^#/, "");
    if (!h) return;
    const parts: Record<string, string> = {};
    h.split("&").forEach((p) => {
      const kv = p.split("=");
      parts[kv[0]] = kv[1] == null ? "" : decodeURIComponent(kv[1]);
    });
    const v = parts.v || "";
    const fullData = data || stateRef.current!.state.fullData;
    if (!fullData || !fullData.nodes.length) return;
    const cam = parts.cam ? parseCam(parts.cam) : null;
    const flags = {
      hideIslands: parts.islands === "1" || location.search.indexOf("hideislands") !== -1,
      showAuthors: parts.authors !== "0",
      fullData: data, // 首载深链:显式传入刚加载的全量图,避免 state 尚未刷新
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
            if (hops > 1) expandRippleDebounced(hops, id, data);
          }).catch(() => dispatch({ type: "SET_TOAST", msg: "加载作品详情失败" }));
        } else {
          renderAuthorView(node, flags);
        }
      }
    } else if (v.indexOf("author:") === 0) {
      const seg = v.slice(7).split(":");
      const id = seg[0];
      const hops = parseInt(seg[1], 10) || 1;
      const node = fullData.nodes.find((n) => n.id === id);
      if (node) renderAuthorView(node, { ...flags, hops });
    } else if (v.indexOf("path:") === 0) {
      const seg = v.slice(5).split(",");
      renderPath(seg[0], seg[1], flags);
    } else if (v === "main" || cam || flags.hideIslands || !flags.showAuthors) {
      renderMain(cam ? { camera: cam } : {}, fullData, flags);
    }
  }, [dispatch]);

  // 管理令牌有效性驱动"数据管理"按钮显隐:有 token 时启动校验,有效才显示
  useEffect(() => {
    const token = getAdminToken();
    if (!token) return;
    validateAdminToken(token).then((ok) => {
      if (ok) dispatch({ type: "SET_ADMIN_READY", value: true });
      else clearAdminToken();
    });
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
        const urlParams = new URLSearchParams(location.search);
        const wantAdmin = urlParams.has("admin") || (location.hash || "").indexOf("admin") !== -1;
        if (wantAdmin) {
          dispatch({ type: "SET_ADMIN", open: true }); // 深链直达数据管理页
        }
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
      if (isMobileLayout()) return; // 移动端侧栏/详情由手势控制,禁用边缘悬停呼出
      const left = document.getElementById("sidebar-left");
      const right = document.getElementById("panel");
      if (left && e.clientX < 8) left.classList.add("show");
      if (right && e.clientX > window.innerWidth - 8) right.classList.add("show");
    };
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, []);

  // 浏览器前进/后退或手动修改 hash 时导航;popstate/focus 兜底地址栏编辑(omnibox 回车可能只触发其一)
  useEffect(() => {
    let lastFocusHash = location.hash;
    const onHashChange = () => {
      lastFocusHash = location.hash;
      applyHash();
    };
    const onFocus = () => {
      if (location.hash !== lastFocusHash) applyHash(); // 失焦期间 hash 被改动(地址栏编辑)才处理
      lastFocusHash = location.hash;
    };
    window.addEventListener("hashchange", onHashChange);
    window.addEventListener("popstate", onHashChange);
    window.addEventListener("focus", onFocus);
    return () => {
      window.removeEventListener("hashchange", onHashChange);
      window.removeEventListener("popstate", onHashChange);
      window.removeEventListener("focus", onFocus);
    };
  }, [applyHash]);

  return (
    <div className="app-shell">
      <GraphCanvas />
      <Sidebar />
      <Panel />
      <Toast />
      <Guide />
      {state.adminOpen && (
        <ChunkBoundary>
          <Suspense fallback={null}>
            <Admin />
          </Suspense>
        </ChunkBoundary>
      )}
      {state.contributeOpen && (
        <ChunkBoundary>
          <Suspense fallback={null}>
            <Contribute />
          </Suspense>
        </ChunkBoundary>
      )}
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
