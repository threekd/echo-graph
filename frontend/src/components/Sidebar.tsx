import { useState, useEffect, useRef, type ChangeEvent } from "react";
import { useApp } from "../store";
import { search } from "../lib/api";
import { buildWorkLookups, islandWorkCount, type WorkLookups } from "../lib/graphData";
import {
  renderMain, renderPath, selectNode, expandRippleDebounced, expandAuthorDebounced, reRenderRipple, reRenderAuthor, syncUrl,
} from "../lib/graph";

export default function Sidebar() {
  const { state, dispatch } = useApp();
  const [q, setQ] = useState("");
  const [qResults, setQResults] = useState<any[]>([]);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [fromOpen, setFromOpen] = useState(false);
  const [toOpen, setToOpen] = useState(false);
  const expandTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lookups = useRef<WorkLookups>({ workLookup: {}, workById: {}, options: [] });
  const expandText = state.expandHops + " 级";

  useEffect(() => {
    lookups.current = buildWorkLookups(state.fullData);
  }, [state.fullData]);

  useEffect(() => {
    if (!q.trim()) { setQResults([]); return; }
    const t = setTimeout(() => {
      search(q.trim())
        .then((r) => setQResults(r.hits || []))
        .catch(() => { setQResults([]); dispatch({ type: "SET_TOAST", msg: "搜索失败" }); });
    }, 200);
    return () => clearTimeout(t);
  }, [q, dispatch]);

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
      if (state.currentView === "author") expandAuthorDebounced(hops);
      else expandRippleDebounced(hops);
    }, 400);
  };

  // 起点/终点作品建议列表:按输入文本过滤,点选已存在作品(可自由输入,提交时校验)
  const filterOptions = (query: string) => {
    const q = query.trim().toLowerCase();
    const all = lookups.current.options;
    return q ? all.filter((o) => o.value.toLowerCase().includes(q)).slice(0, 50) : all.slice(0, 50);
  };

  // 过滤开关变化后按当前视图重新渲染(保持相机),主/涟漪视图由渲染函数自行同步 URL
  const rerenderCurrentView = (overrides: { hideIslands?: boolean; showAuthors?: boolean }) => {
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
      });
    }
  };

  const onToggleAuthors = (e: ChangeEvent<HTMLInputElement>) => {
    const value = e.target.checked;
    dispatch({ type: "SET_SHOW_AUTHORS", value });
    rerenderCurrentView({ showAuthors: value });
  };

  const onToggleIslands = (e: ChangeEvent<HTMLInputElement>) => {
    const value = e.target.checked;
    dispatch({ type: "SET_HIDE_ISLANDS", value });
    rerenderCurrentView({ hideIslands: value });
    const n = islandWorkCount(state.fullData);
    dispatch({
      type: "SET_TOAST",
      msg: value ? `孤岛星已隐藏:${n} 部作品无提及关系` : `孤岛星已显示:${n} 部无提及关系的作品恢复显示`,
    });
  };

  const backMain = () => {
    renderMain({});
    dispatch({ type: "SET_PANEL", panel: { type: "empty" } });
  };

  return (
    <>
      <div id="sidebar-zone-left"><span className="zone-icon">◀</span></div>
      <aside
        id="sidebar-left"
        onMouseLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) e.currentTarget.classList.remove("show");
        }}
      >
        <div className="brand">
          <h1>The Echo Graph</h1>
          <span className="badge">回声图谱</span>
          <div className="store-badge">
            数据源:{state.storeName === "neo4j" ? "Neo4j" : state.storeName === "json" ? "JSON 兜底" : "加载中…"}
          </div>
        </div>
        <nav>
          <div id="view-status">视图:{viewLabel(state.currentView)}</div>
          <button
            id="btn-back-main" className="side-btn"
            style={{ display: state.currentView === "main" ? "none" : "block" }}
            onClick={backMain}
          >
            返回全部图谱
          </button>
          <div className="field">
            <input id="q" value={q} placeholder="搜索作家 / 作品…" onChange={(e) => setQ(e.target.value)} />
            {qResults.length > 0 && (
              <ul id="q-results" style={{ display: "block" }}>
                {qResults.map((h) => (
                  <li key={h.id} onClick={() => { setQ(h.label); setQResults([]); selectNode(h.id); }}>
                    <strong>{h.label}</strong> <small>{h.sub || ""}</small>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="path-box">
            <div className="path-fields">
              <div className="path-field">
                <input
                  id="from"
                  value={from}
                  placeholder="起点作品"
                  onChange={(e) => setFrom(e.target.value)}
                  onFocus={() => setFromOpen(true)}
                  onBlur={() => setFromOpen(false)}
                  onKeyDown={(e) => { if (e.key === "Escape") setFromOpen(false); }}
                />
                {fromOpen && filterOptions(from).length > 0 && (
                  <ul id="from-results" style={{ display: "block" }}>
                    {filterOptions(from).map((o) => (
                      <li
                        key={o.id}
                        onMouseDown={(e) => {
                          e.preventDefault(); // 先于 blur 触发,避免失焦关闭
                          setFrom(o.value);
                          setFromOpen(false);
                        }}
                      >
                        {o.value}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <button id="btn-swap" title="交换起终点" onClick={() => { setFrom(to); setTo(from); }}>⇅</button>
              <div className="path-field">
                <input
                  id="to"
                  value={to}
                  placeholder="终点作品"
                  onChange={(e) => setTo(e.target.value)}
                  onFocus={() => setToOpen(true)}
                  onBlur={() => setToOpen(false)}
                  onKeyDown={(e) => { if (e.key === "Escape") setToOpen(false); }}
                />
                {toOpen && filterOptions(to).length > 0 && (
                  <ul id="to-results" style={{ display: "block" }}>
                    {filterOptions(to).map((o) => (
                      <li
                        key={o.id}
                        onMouseDown={(e) => {
                          e.preventDefault(); // 先于 blur 触发,避免失焦关闭
                          setTo(o.value);
                          setToOpen(false);
                        }}
                      >
                        {o.value}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
            <button id="btn-path" onClick={doPath}>寻找路径</button>
          </div>
          <div id="expand-bar" style={{ display: state.currentView === "ripple" || state.currentView === "author" ? "flex" : "none" }}>
            <span className="expand-label">扩散范围</span>
            <input
              type="range" id="expand-range" min="1" max="8" step="1" value={state.expandHops}
              onChange={(e) => onExpand(parseInt(e.target.value, 10) || 1)}
            />
            <span id="expand-value">{expandText}</span>
          </div>
        </nav>
        <div className="sidebar-bottom">
          <label className="opt">
            <input
              type="checkbox" id="show-authors" checked={state.showAuthors}
              onChange={onToggleAuthors}
            />
            <span>显示作家节点</span>
          </label>
          <label className="opt">
            <input
              type="checkbox" id="hide-islands" checked={state.hideIslands}
              onChange={onToggleIslands}
            />
            <span>隐藏孤岛星</span>
          </label>
          <button id="btn-admin" className="side-btn" onClick={() => dispatch({ type: "SET_ADMIN", open: true })}>数据管理</button>
        </div>
      </aside>
    </>
  );
}

function viewLabel(view: string): string {
  return view === "main" ? "全图谱" : view === "ripple" ? "涟漪" : view === "author" ? "作者" : "提及链";
}
