import { lazy, Suspense, useCallback, useEffect, useRef } from "react";
import { flushSync } from "react-dom";
import {
  AppProvider,
  useApp,
  type AppAction,
  type AppState,
  type GraphData,
} from "./store";
import GraphCanvas from "./components/GraphCanvas";
import Sidebar from "./components/Sidebar";
import Panel from "./components/Panel";
import Toast from "./components/Toast";
import Guide from "./components/Guide";
import AuthModal from "./components/AuthModal";
import ChunkBoundary from "./components/ChunkBoundary";
import {
  loadGraphData, loadSpaceGraph, loadStats, spaceFromParam, spaceUserId, workDetail, type Space,
} from "./lib/api";
import { fetchMe } from "./lib/auth";
import { isMobileLayout, useMobileGestures } from "./lib/mobileGestures";
import { parseCam, parseHashParams } from "./lib/hash";
import {
  renderMain, setStateRef, renderRipple, renderAuthorView, renderPath, expandRippleDebounced,
  isSelfWrittenHash,
} from "./lib/graph";
import { enterSpace } from "./lib/space";
import { setOnCameraChange } from "./lib/renderer";

// 管理页与贡献弹窗按需加载(普通用户默认不可见,不打进首屏包)
const Admin = lazy(() => import("./components/Admin"));
const Contribute = lazy(() => import("./components/Contribute"));

function AppContent() {
  const { state, dispatch } = useApp();
  const stateRef = useRef<{ state: AppState; dispatch: (a: AppAction) => void } | null>(null);
  stateRef.current = { state, dispatch };
  useMobileGestures(state.pinLeft, state.pinRight);
  const backSentinelPushed = useRef(false);
  // 同一 hash 在短时间内(hashchange/popstate/focus 多事件)只处理一次
  const lastAppliedHash = useRef<string | null>(null);
  const lastAppliedAt = useRef(0);
  // 防止空间切换加载期间/回退公共星云时,对同一 hash 重复触发切换
  const lastAppliedSpace = useRef<Space | null>(null);

  // 切换空间上下文(hash 的 space 参数变化):加载目标星云并应用;未登录/不可访问回退公共星云
  const applyHashSpace = useCallback((target: Space): Promise<{ data: GraphData }> => {
    const apply = (space: Space, data: GraphData) => {
      const owner =
        space === "public" ? "public"
        : space === "mine"
          ? ((data as any).owner?.nickname || (data as any).owner?.username || "我的星云")
          : ((data as any).displayName || "未知星云");
      enterSpace(dispatch, space, data, owner, (data as any).owner, { flush: true });
      return { data };
    };
    if (target === "mine") {
      return fetchMe().then((user) => {
        if (user) {
          dispatch({ type: "SET_USER", user });
          return loadGraphData("mine").then((d) => apply("mine", d));
        }
        dispatch({ type: "SET_TOAST", msg: "请先登录,已回到公共星云", kind: "info" });
        return loadGraphData("public").then((d) => apply("public", d));
      });
    }
    if (target !== "public") {
      const uid = spaceUserId(target);
      return loadSpaceGraph(uid!)
        .then((d) => apply(target, d))
        .catch(() => {
          dispatch({ type: "SET_TOAST", msg: "该星云不可访问,已回到公共星云", kind: "info" });
          return loadGraphData("public").then((d) => apply("public", d));
        });
    }
    return loadGraphData("public").then((d) => apply("public", d));
  }, [dispatch]);

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
      const st = stateRef.current!.state;
      if (st.user) {
        dispatch({ type: "SET_ADMIN", open: true });
      } else {
        dispatch({ type: "SET_AUTH", open: true });
        dispatch({ type: "SET_TOAST", msg: "请先登录,再管理你的星云数据", kind: "info" });
      }
      return;
    }
    const parts = parseHashParams(location.hash);
    const v = parts.v || "";
    const st = stateRef.current!.state;
    // hash 的 space 参数与当前星云不一致时,先切换星云再应用视图
    const targetSpace = spaceFromParam(parts.space);
    if (targetSpace && targetSpace !== st.space && lastAppliedSpace.current !== targetSpace) {
      lastAppliedSpace.current = targetSpace;
      applyHashSpace(targetSpace).then(({ data: newData }) => { applyHash(newData); });
      return;
    }
    lastAppliedSpace.current = null;
    const fullData = data || st.fullData;
    if (!fullData || !fullData.nodes.length) return;
    const cam = parts.cam ? parseCam(parts.cam) : null;
    const flags = {
      hideIslands: parts.islands === "1" || location.search.indexOf("hideislands") !== -1,
      showAuthors: parts.authors !== "0",
      fullData: data, // 首载深链:显式传入刚加载的全量图,避免 state 尚未刷新
    };
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
            workDetail(id, st.space).then((d) => {
              renderRipple(d, hops, flags);
              // 手机端深链也保存节点信息,但面板不自动呼出
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
  }, [dispatch, applyHashSpace]);

  // 启动时恢复会话(带 httpOnly Cookie,浏览器自动携带):有登录态则展示用户信息
  useEffect(() => {
    fetchMe().then((user) => {
      if (user) dispatch({ type: "SET_USER", user });
      // 深链 ?admin / #v=admin:仅 admin 角色进入数据管理
      const wantAdmin =
        new URLSearchParams(location.search).has("admin") ||
        (location.hash || "").indexOf("admin") !== -1;
      if (wantAdmin) {
        if (user) {
          dispatch({ type: "SET_ADMIN", open: true });
        } else {
          dispatch({ type: "SET_AUTH", open: true });
          dispatch({ type: "SET_TOAST", msg: "请先登录,再管理你的星云数据", kind: "info" });
        }
      }
    });
  }, [dispatch]);

  useEffect(() => {
    setStateRef(stateRef);
    setOnCameraChange((camera) => {
      dispatch({ type: "SET_CAMERA", camera });
    });
    let cancelled = false;
    // 首载空间上下文:优先取 hash 的 space 参数(public / mine / <用户id>)
    let target: Space = spaceFromParam(parseHashParams(location.hash).space) || "public";
    let mineOwner = "我的星云";

    const loadTarget = async (): Promise<GraphData> => {
      if (target === "mine") {
        const user = await fetchMe();
        if (user) {
          dispatch({ type: "SET_USER", user });
          mineOwner = (user.nickname || "").trim() || (user.username || "") || "我的星云";
          return loadGraphData("mine");
        }
        target = "public";
        dispatch({ type: "SET_TOAST", msg: "请先登录,已回到公共星云", kind: "info" });
        return loadGraphData("public");
      }
      if (target !== "public") {
        const uid = spaceUserId(target);
        try {
          return await loadSpaceGraph(uid!);
        } catch {
          target = "public";
          dispatch({ type: "SET_TOAST", msg: "该星云不可访问,已回到公共星云", kind: "info" });
          return loadGraphData("public");
        }
      }
      return loadGraphData("public");
    };

    Promise.all([loadTarget(), loadStats()])
      .then(([data, stats]) => {
        if (cancelled) return;
        const owner =
          target === "public" ? "public"
          : target === "mine" ? mineOwner
          : ((data as any).displayName || "未知星云");
        // flushSync 保证 applyHash/renderMain 读到的是最新 space
        flushSync(() => {
          dispatch({ type: "SET_DATA", data });
          dispatch({ type: "SET_SPACE", space: target });
          dispatch({ type: "SET_SPACE_OWNER", owner });
          dispatch({ type: "SET_SPACE_PROFILE", profile: (data as any).owner || null });
          dispatch({ type: "SET_STORE", name: (stats && stats.store) || "" });
        });
        if (location.hash.replace(/^#/, "")) {
          applyHash(data);
        } else {
          renderMain({}, data);
        }
      })
      .catch((err) => {
        if (!cancelled) dispatch({ type: "SET_TOAST", msg: "加载图谱失败: " + err.message });
      });
    return () => { cancelled = true; };
  }, [applyHash, dispatch]);

  // 恢复钉住状态(桌面):钉住的栏在加载后保持展开;状态记忆在 localStorage
  useEffect(() => {
    if (isMobileLayout()) return;
    let pinL = false;
    let pinR = false;
    try {
      pinL = localStorage.getItem("echo_graph_pin_left") === "1";
      pinR = localStorage.getItem("echo_graph_pin_right") === "1";
    } catch {
      /* localStorage 不可用时忽略 */
    }
    if (!pinL && !pinR) return;
    if (pinL) dispatch({ type: "SET_PIN_LEFT", value: true });
    if (pinR) dispatch({ type: "SET_PIN_RIGHT", value: true });
    const raf = requestAnimationFrame(() => {
      if (pinL) document.getElementById("sidebar-left")?.classList.add("show");
      if (pinR) document.getElementById("panel")?.classList.add("show");
    });
    return () => cancelAnimationFrame(raf);
  }, [dispatch]);

  // 手机端返回:有栏先收栏;非主视图回主视图;主视图且无栏则放行系统返回。
  // 加载时压入一个"哨兵"历史条目,视图变化用 replaceState 改写 URL(不产生视图历史),
  // 因此每次返回都先回到哨兵之下的条目,由这里决定消费(补回哨兵)还是放行。
  useEffect(() => {
    if (!isMobileLayout()) return;
    if (!backSentinelPushed.current) {
      history.pushState({ litnebulaBack: true }, "", location.href);
      backSentinelPushed.current = true;
    }
    const onPopState = () => {
      const s = document.getElementById("sidebar-left");
      const p = document.getElementById("panel");
      const barsOpen =
        !!(s && s.classList.contains("show")) || !!(p && p.classList.contains("show"));
      const st = stateRef.current && stateRef.current.state;
      const notMain = !!st && st.currentView !== "main";
      if (barsOpen) {
        if (s) s.classList.remove("show");
        if (p) p.classList.remove("show");
      } else if (notMain) {
        renderMain({}); // 回主视图:详情栏内容随之清空并收起
      } else {
        return; // 主视图且无栏:放行,让浏览器退出/回上一页
      }
      // 消费本次返回后补一个哨兵条目,保证下一次返回仍可拦截
      history.pushState({ litnebulaBack: true }, "", location.href);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [dispatch]);

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
      if (isMobileLayout()) return; // 手机端返回由应用层接管,不按 URL 历史导航
      lastFocusHash = location.hash;
      applyHash();
    };
    const onFocus = () => {
      if (isMobileLayout()) return;
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
      {state.authOpen && <AuthModal />}
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
