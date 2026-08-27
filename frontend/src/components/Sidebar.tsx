/* 侧边栏容器:Tab 外壳 + 全部状态与处理函数。

   Tab 内容按职责拆分到 components/sidebar/:
   - SpaceTab.tsx    星云(品牌/切换/跃迁/搜索/路径/扩散/过滤)
   - MineTab.tsx     我的(个人资料 + 关注/粉丝)
   - SettingsTab.tsx 设置(账号 + 星云可见性 + 退出入口)
   - LogoutModal.tsx 退出确认弹窗 */

import { useState, useEffect, useRef, type ChangeEvent, type KeyboardEvent } from "react";
import { useApp } from "../store";
import {
  jumpToRandomSpace, loadFollowers, loadFollowing, loadGraphData, loadSpaceGraph,
  search, type FollowUser, type Space,
} from "../lib/api";
import { logout, updateProfile, userDisplayName } from "../lib/auth";
import { buildWorkLookups, islandWorkCount, type WorkLookups } from "../lib/graphData";
import { enterSpace } from "../lib/space";
import PinButton from "./PinButton";
import {
  renderMain, renderPath, selectNode, expandRippleDebounced, expandAuthorDebounced, reRenderRipple, reRenderAuthor, syncUrl,
} from "../lib/graph";
import SpaceTab from "./sidebar/SpaceTab";
import MineTab from "./sidebar/MineTab";
import SettingsTab from "./sidebar/SettingsTab";
import LogoutModal from "./sidebar/LogoutModal";

export default function Sidebar() {
  const { state, dispatch } = useApp();
  const [q, setQ] = useState("");
  const [qResults, setQResults] = useState<any[]>([]);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [fromOpen, setFromOpen] = useState(false);
  const [toOpen, setToOpen] = useState(false);
  const [qActive, setQActive] = useState(-1);
  const expandTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 扩散范围数字输入框:本地字符串态允许输入中间值,提交时收敛到 [1, expandMax]
  const [expandInput, setExpandInput] = useState(String(state.expandHops));
  const [logoutConfirm, setLogoutConfirm] = useState(false);
  // 侧边栏功能 Tab:space = 星云(主内容);mine = 我的(个人资料 + 关注/粉丝);
  // messages = 消息(第二阶段通知);settings = 设置(账号 + 星云可见性)
  const [tab, setTab] = useState<"space" | "mine" | "messages" | "settings">("space");
  const [profileForm, setProfileForm] = useState<{ nickname: string; bio: string }>({
    nickname: "",
    bio: "",
  });
  const [profileError, setProfileError] = useState("");
  const [profileBusy, setProfileBusy] = useState(false);
  const [following, setFollowing] = useState<FollowUser[]>([]);
  const [followers, setFollowers] = useState<FollowUser[]>([]);
  const switchSpace = (space: Space) => {
    if (space === "mine" && !state.user) {
      dispatch({ type: "SET_AUTH", open: true }); // 我的星云需登录
      return;
    }
    dispatch({ type: "SET_SPACE", space });
    dispatch({
      type: "SET_SPACE_OWNER",
      owner: space === "public" ? "public" : (userDisplayName(state.user) || "我的星云"),
    });
    loadGraphData(space)
      .then((data) => {
        enterSpace(
          dispatch,
          space,
          data,
          space === "public" ? "public" : userDisplayName(state.user) || "我的星云",
          (data as any).owner,
          { render: true }
        );
      })
      .catch((e) =>
        dispatch({
          type: "SET_TOAST",
          msg: "加载「" + (space === "mine" ? "我的星云" : "公共星云") + "」失败: " + e.message,
          kind: "error",
        })
      );
  };

  // 星云可见性自服务切换(公开 = 可被星际跃迁访问;仅自己 = 游客 404)
  const setSpaceVisibility = (next: "public" | "private") => {
    if (!state.user) return;
    updateProfile({ space_visibility: next })
      .then((r) => {
        if (r.user) {
          dispatch({ type: "SET_USER", user: r.user });
          dispatch({
            type: "SET_TOAST",
            msg: next === "private" ? "你的星云已设为仅自己可见" : "你的星云已设为公开(可被跃迁)",
            kind: "success",
          });
        } else {
          dispatch({ type: "SET_TOAST", msg: r.error || "设置失败", kind: "error" });
        }
      })
      .catch((e) => dispatch({ type: "SET_TOAST", msg: "设置失败: " + e.message, kind: "error" }));
  };

  // 登录用户变化时,设置页表单同步为最新资料(保存成功后也会自动刷新)
  useEffect(() => {
    if (state.user) {
      setProfileForm({
        nickname: state.user.nickname || "",
        bio: state.user.bio || "",
      });
    }
  }, [state.user]);

  const saveProfile = () => {
    setProfileError("");
    setProfileBusy(true);
    updateProfile({
      nickname: profileForm.nickname.trim() || null,
      bio: profileForm.bio.trim() || null,
    })
      .then((r) => {
        if (r.user) {
          dispatch({ type: "SET_USER", user: r.user });
          setProfileForm({
            nickname: r.user.nickname || "",
            bio: r.user.bio || "",
          });
          setProfileError("");
          dispatch({ type: "SET_TOAST", msg: "个人资料已保存", kind: "success" });
        } else {
          setProfileError(r.error || "保存失败");
        }
      })
      .catch((e) => setProfileError("保存失败: " + e.message))
      .finally(() => setProfileBusy(false));
  };

  const doJump = () => {
    // 星际跃迁浏览他人星云需登录(与「我的星云」「点亮星空」一致)
    if (!state.user) {
      dispatch({ type: "SET_AUTH", open: true });
      dispatch({ type: "SET_TOAST", msg: "请先登录,再使用星际跃迁", kind: "info" });
      return;
    }
    jumpToRandomSpace()
      .then((d) => {
        // 跃迁后进入该星云的空间上下文:后续搜索/详情/扩散/路径都路由到 /api/space/{id}
        enterSpace(
          dispatch,
          `space:${d.spaceId}`,
          d,
          d.displayName || "未知星云",
          (d as any).owner,
          { render: true }
        );
        dispatch({
          type: "SET_TOAST",
          msg: "已跃迁到「" + (d.displayName || "未知星云") + "」的星云",
          kind: "info",
        });
      })
      .catch((e) =>
        dispatch({ type: "SET_TOAST", msg: "跃迁失败: " + e.message, kind: "error" })
      );
  };

  // 定向跃迁到指定用户星云(关注/粉丝列表入口)
  const jumpToSpace = (userId: string, displayName: string) => {
    loadSpaceGraph(userId)
      .then((d) => {
        enterSpace(
          dispatch,
          `space:${userId}`,
          d,
          displayName || "未知星云",
          (d as any).owner,
          { render: true }
        );
        dispatch({
          type: "SET_TOAST",
          msg: "已跃迁到「" + (displayName || "未知星云") + "」的星云",
          kind: "info",
        });
      })
      .catch((e) =>
        dispatch({ type: "SET_TOAST", msg: "跃迁失败: " + e.message, kind: "error" })
      );
  };

  // 「我的」Tab 打开(或登录态/当前空间变化)时刷新关注/粉丝列表
  useEffect(() => {
    if (tab !== "mine" || !state.user) return;
    let cancelled = false;
    Promise.all([loadFollowing(), loadFollowers()])
      .then(([f, fs]) => {
        if (cancelled) return;
        setFollowing(f.items || []);
        setFollowers(fs.items || []);
      })
      .catch(() => { /* 列表加载失败静默,下次进入重试 */ });
    return () => { cancelled = true; };
  }, [tab, state.user, state.space]);

  const lookups = useRef<WorkLookups>({ workLookup: {}, workById: {}, options: [] });
  const sidebarRef = useRef<HTMLElement | null>(null);
  const composingRef = useRef(false);
  const currentViewRef = useRef(state.currentView);
  currentViewRef.current = state.currentView;
  // 外部(深链/视图切换)改变扩散级数时同步输入框显示
  useEffect(() => {
    setExpandInput(String(state.expandHops));
  }, [state.expandHops]);

  useEffect(() => {
    lookups.current = buildWorkLookups(state.fullData);
  }, [state.fullData]);

  // 深链 #v=path:... 打开后回填路径输入框
  useEffect(() => {
    if (state.pathInputs.from) setFrom(state.pathInputs.from);
    if (state.pathInputs.to) setTo(state.pathInputs.to);
  }, [state.pathInputs]);

  useEffect(() => {
    if (!q.trim()) { setQResults([]); return; }
    const t = setTimeout(() => {
      search(q.trim(), state.space)
        .then((r) => { setQResults(r.hits || []); setQActive(-1); })
        .catch(() => { setQResults([]); dispatch({ type: "SET_TOAST", msg: "搜索失败" }); });
    }, 200);
    return () => clearTimeout(t);
  }, [q, state.space, dispatch]);

  // 输入聚焦或中文输入法组合期间不隐藏侧栏(候选框弹出时鼠标已不在侧栏内)
  useEffect(() => {
    const panel = sidebarRef.current;
    if (!panel) return;
    const onCompositionStart = () => { composingRef.current = true; };
    const onCompositionEnd = () => { composingRef.current = false; };
    panel.addEventListener("compositionstart", onCompositionStart, true);
    panel.addEventListener("compositionend", onCompositionEnd, true);
    return () => {
      panel.removeEventListener("compositionstart", onCompositionStart, true);
      panel.removeEventListener("compositionend", onCompositionEnd, true);
    };
  }, []);

  const keepSidebarOpen = () => {
    if (composingRef.current) return true; // 中文输入法组合期间不隐藏
    const ae = document.activeElement;
    if (!ae || !sidebarRef.current || !sidebarRef.current.contains(ae)) return false;
    // 仅文本输入(搜索/路径)聚焦时保持打开;复选框/按钮点击后焦点残留不应阻止收起
    return ae instanceof HTMLInputElement
      && (ae.type === "text" || ae.type === "search" || ae.type === "number");
  };

  const chooseHit = (h: any) => {
    setQ(h.label);
    setQResults([]);
    setQActive(-1);
    selectNode(h.id);
  };

  // 搜索下拉键盘导航:↑↓ 选择,Enter 确认
  const onSearchKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    const n = qResults.length;
    if (!n) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setQActive((v) => (v + 1) % n);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setQActive((v) => (v - 1 + n) % n);
    } else if (e.key === "Enter") {
      e.preventDefault();
      chooseHit(qActive >= 0 && qActive < n ? qResults[qActive] : qResults[0]);
    }
  };

  const doPath = () => {
    const fid = lookups.current.workLookup[from.trim()];
    const tid = lookups.current.workLookup[to.trim()];
    if (!fid || !tid) {
      dispatch({ type: "SET_TOAST", msg: "请从下拉列表中选择两部作品" });
      return;
    }
    renderPath(fid, tid).then((result) => {
      if (result === undefined) return; // 网络错误已由 renderPath 提示
      if (!result) {
        dispatch({ type: "SET_TOAST", msg: "未找到提及链" });
        return;
      }
      dispatch({ type: "SET_PANEL", panel: { type: "path", result, f: from.trim(), t: to.trim() } });
    });
  };

  const onExpand = (hops: number) => {
    dispatch({ type: "SET_EXPAND", value: hops });
    if (expandTimer.current) clearTimeout(expandTimer.current);
    expandTimer.current = setTimeout(() => {
      if (currentViewRef.current === "author") expandAuthorDebounced(hops);
      else expandRippleDebounced(hops);
    }, 400);
  };

  // 扩散级数收敛到 [1, expandMax](与旧滑条边界一致)
  const clampExpand = (hops: number): number =>
    Math.min(Math.max(Math.round(hops) || 1, 1), Math.max(state.expandMax, 1));

  // ± 按钮步进
  const stepExpand = (delta: number) => {
    const next = clampExpand(state.expandHops + delta);
    setExpandInput(String(next));
    onExpand(next);
  };

  // 输入框直接输入:只接受正整数;合法时立即生效(自动收敛到上限)
  const onExpandInputChange = (raw: string) => {
    if (raw !== "" && !/^\d+$/.test(raw)) return;
    setExpandInput(raw);
    const n = parseInt(raw, 10);
    if (n >= 1) onExpand(clampExpand(n));
  };

  // 失焦/回车提交:空值或非法值回退到当前级数
  const commitExpandInput = () => {
    const n = parseInt(expandInput, 10);
    const next = n >= 1 ? clampExpand(n) : state.expandHops;
    setExpandInput(String(next));
    if (next !== state.expandHops) onExpand(next);
  };

  // 起点/终点作品建议列表:按输入文本过滤,点选已存在作品(可自由输入,提交时校验)
  const filterOptions = (query: string) => {
    const q = query.trim().toLowerCase();
    const all = lookups.current.options;
    return q ? all.filter((o) => o.value.toLowerCase().includes(q)).slice(0, 50) : all.slice(0, 50);
  };

  // 过滤开关变化后按当前视图重新渲染(保持相机),主/涟漪视图由渲染函数自行同步 URL
  const rerenderCurrentView = (overrides: {
    hideIslands?: boolean;
    showAuthors?: boolean;
    readingFilter?: import("../store").ReadingFilter;
  }) => {
    if (state.currentView === "main") {
      renderMain({ preserveCamera: true }, null, overrides);
    } else if (state.currentView === "ripple") {
      reRenderRipple();
    } else if (state.currentView === "author") {
      reRenderAuthor(overrides);
    } else {
      syncUrl({
        view: state.currentView,
        hideIslands: overrides.hideIslands != null ? overrides.hideIslands : state.hideIslands,
        showAuthors: overrides.showAuthors != null ? overrides.showAuthors : state.showAuthors,
        readingFilter: overrides.readingFilter != null ? overrides.readingFilter : state.readingFilter,
      });
    }
  };

  const onToggleAuthors = (e: ChangeEvent<HTMLInputElement>) => {
    const value = e.target.checked;
    dispatch({ type: "SET_SHOW_AUTHORS", value });
    rerenderCurrentView({ showAuthors: value });
    dispatch({ type: "SET_TOAST", msg: value ? "已显示作家节点" : "已隐藏作家节点", kind: "info" });
  };

  const onToggleWorkLabels = (e: ChangeEvent<HTMLInputElement>) => {
    const value = e.target.checked;
    dispatch({ type: "SET_SHOW_WORK_LABELS", value });
    // 标签显隐由 GraphCanvas effect 直接驱动渲染器,无需重新布局
    syncUrl({ view: state.currentView, showWorkLabels: value });
    dispatch({ type: "SET_TOAST", msg: value ? "已显示作品名称" : "已隐藏作品名称", kind: "info" });
  };

  const onReadingFilter = (e: ChangeEvent<HTMLSelectElement>) => {
    const value = e.target.value as import("../store").ReadingFilter;
    dispatch({ type: "SET_READING_FILTER", value });
    rerenderCurrentView({ readingFilter: value });
  };

  const onToggleIslands = (e: ChangeEvent<HTMLInputElement>) => {
    const value = e.target.checked;
    dispatch({ type: "SET_HIDE_ISLANDS", value });
    rerenderCurrentView({ hideIslands: value });
    const n = islandWorkCount(state.fullData);
    dispatch({
      type: "SET_TOAST",
      msg: value ? `${n} 部作品已隐藏` : `${n} 部作品已显示`,
      kind: "info",
    });
  };

  const backMain = () => {
    renderMain({});
    dispatch({ type: "SET_PANEL", panel: { type: "empty" } });
  };

  // 钉住左侧功能栏:钉住后不再随鼠标移出自动隐藏
  const togglePinLeft = () => {
    const next = !state.pinLeft;
    dispatch({ type: "SET_PIN_LEFT", value: next });
    try {
      localStorage.setItem("echo_graph_pin_left", next ? "1" : "");
    } catch {
      /* ignore */
    }
    if (next) document.getElementById("sidebar-left")?.classList.add("show");
    // 取消钉住不立即收起,保持当前展开状态,下一次移出再按原逻辑隐藏
  };

  return (
    <>
      <div id="sidebar-zone-left"><span className="zone-icon">◀</span></div>
      <aside
        id="sidebar-left"
        ref={sidebarRef}
        onMouseLeave={(e) => {
          if (state.pinLeft) return; // 钉住:不自动隐藏
          if (keepSidebarOpen()) return; // 输入聚焦/输入法组合期间不隐藏
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) e.currentTarget.classList.remove("show");
        }}
      >
        {/* 钉住仅作用于星云 Tab;设置页不显示,避免与账号卡片重叠 */}
        {tab === "space" && (
          <PinButton
            id="btn-pin-left"
            pinned={state.pinLeft}
            title={state.pinLeft ? "取消钉住(移出自动隐藏)" : "钉住(不再自动隐藏)"}
            onToggle={togglePinLeft}
          />
        )}
        {/* Tab 列(类 VS Code Activity Bar):星云 / 我的 / 消息 / 设置 */}
        <div className="sidebar-tabs" role="tablist" aria-label="侧边栏功能">
          <button
            id="tab-space"
            className={"sidebar-tab" + (tab === "space" ? " active" : "")}
            role="tab"
            aria-selected={tab === "space"}
            title="星云"
            onClick={() => setTab("space")}
          >
            <span className="sidebar-tab-icon">✦</span>
            <span className="sidebar-tab-label">星云</span>
          </button>
          <button
            id="tab-mine"
            className={"sidebar-tab" + (tab === "mine" ? " active" : "")}
            role="tab"
            aria-selected={tab === "mine"}
            title="我的(个人资料与关注)"
            onClick={() => setTab("mine")}
          >
            <span className="sidebar-tab-icon">◉</span>
            <span className="sidebar-tab-label">我的</span>
          </button>
          <button
            id="tab-messages"
            className={"sidebar-tab" + (tab === "messages" ? " active" : "")}
            role="tab"
            aria-selected={tab === "messages"}
            title="消息(第二阶段)"
            onClick={() => setTab("messages")}
          >
            <span className="sidebar-tab-icon">✉</span>
            <span className="sidebar-tab-label">消息</span>
          </button>
          <button
            id="tab-settings"
            className={"sidebar-tab tab-bottom" + (tab === "settings" ? " active" : "")}
            role="tab"
            aria-selected={tab === "settings"}
            title="设置"
            onClick={() => setTab("settings")}
          >
            <span className="sidebar-tab-icon">⚙</span>
            <span className="sidebar-tab-label">设置</span>
          </button>
        </div>
        <div className="sidebar-content">
          {tab === "space" ? (
            <SpaceTab
              state={state}
              dispatch={dispatch}
              q={q}
              setQ={setQ}
              qResults={qResults}
              qActive={qActive}
              setQResults={setQResults}
              setQActive={setQActive}
              from={from}
              setFrom={setFrom}
              to={to}
              setTo={setTo}
              fromOpen={fromOpen}
              setFromOpen={setFromOpen}
              toOpen={toOpen}
              setToOpen={setToOpen}
              expandInput={expandInput}
              filterOptions={filterOptions}
              chooseHit={chooseHit}
              onSearchKeyDown={onSearchKeyDown}
              doPath={doPath}
              doJump={doJump}
              backMain={backMain}
              stepExpand={stepExpand}
              onExpandInputChange={onExpandInputChange}
              commitExpandInput={commitExpandInput}
              onToggleAuthors={onToggleAuthors}
              onToggleWorkLabels={onToggleWorkLabels}
              onReadingFilter={onReadingFilter}
              onToggleIslands={onToggleIslands}
              switchSpace={switchSpace}
            />
          ) : tab === "mine" ? (
            <MineTab
              state={state}
              dispatch={dispatch}
              profileForm={profileForm}
              setProfileForm={setProfileForm}
              profileError={profileError}
              profileBusy={profileBusy}
              saveProfile={saveProfile}
              following={following}
              followers={followers}
              jumpToSpace={jumpToSpace}
            />
          ) : tab === "messages" ? (
            <div className="settings-pane">
              <div className="settings-section">
                <h3>消息</h3>
                <p className="settings-hint">消息通知功能规划中(第二阶段),敬请期待。</p>
              </div>
            </div>
          ) : (
            <SettingsTab
              state={state}
              dispatch={dispatch}
              setSpaceVisibility={setSpaceVisibility}
              onRequestLogout={() => setLogoutConfirm(true)}
            />
          )}
        </div>
      </aside>
      <LogoutModal
        open={logoutConfirm}
        onCancel={() => setLogoutConfirm(false)}
        onConfirm={() => {
          setLogoutConfirm(false);
          logout().finally(() => dispatch({ type: "SET_USER", user: null }));
          setTab("space"); // 退出后回到星云 Tab
          dispatch({ type: "SET_TOAST", msg: "已退出登录", kind: "info" });
        }}
      />
    </>
  );
}
