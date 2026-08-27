/* 侧边栏「星云」Tab:品牌、空间切换、星际跃迁、搜索、路径、扩散与过滤。

   状态与处理函数由 Sidebar 容器持有并注入(本组件保持无自有状态),拆出后
   Sidebar.tsx 从 839 行降到约 380 行。 */

import type { ChangeEvent, KeyboardEvent } from "react";
import type { Space } from "../../lib/api";
import type { AppAction, AppState } from "../../store";

interface SpaceTabProps {
  state: AppState;
  dispatch: (a: AppAction) => void;
  q: string;
  setQ: (v: string) => void;
  qResults: any[];
  qActive: number;
  setQResults: (v: any[]) => void;
  setQActive: (v: number) => void;
  from: string;
  setFrom: (v: string) => void;
  to: string;
  setTo: (v: string) => void;
  fromOpen: boolean;
  setFromOpen: (v: boolean) => void;
  toOpen: boolean;
  setToOpen: (v: boolean) => void;
  expandInput: string;
  filterOptions: (query: string) => { id: string; value: string }[];
  chooseHit: (h: any) => void;
  onSearchKeyDown: (e: KeyboardEvent<HTMLInputElement>) => void;
  doPath: () => void;
  doJump: () => void;
  backMain: () => void;
  stepExpand: (delta: number) => void;
  onExpandInputChange: (raw: string) => void;
  commitExpandInput: () => void;
  onToggleAuthors: (e: ChangeEvent<HTMLInputElement>) => void;
  onToggleWorkLabels: (e: ChangeEvent<HTMLInputElement>) => void;
  onToggleIslands: (e: ChangeEvent<HTMLInputElement>) => void;
  onReadingFilter: (e: ChangeEvent<HTMLSelectElement>) => void;
  switchSpace: (space: Space) => void;
}

function viewLabel(view: string): string {
  return view === "main" ? "全图谱" : view === "ripple" ? "涟漪" : view === "author" ? "作者" : "提及链";
}

export default function SpaceTab(props: SpaceTabProps) {
  const {
    state, dispatch,
    q, setQ, qResults, qActive, setQResults, setQActive,
    from, setFrom, to, setTo, fromOpen, setFromOpen, toOpen, setToOpen,
    expandInput, filterOptions, chooseHit, onSearchKeyDown,
    doPath, doJump, backMain, stepExpand, onExpandInputChange, commitExpandInput,
    onToggleAuthors, onToggleWorkLabels, onToggleIslands, onReadingFilter, switchSpace,
  } = props;

  return (
    <>
      <div className="brand">
        <h1>Litnebula</h1>
        <span className="beta-badge">beta</span>
        {/* 账号入口已移入「设置」Tab,品牌行不再显示账号角标 */}
        <div className="store-badge">
          数据源:{state.spaceOwner || "public"}
        </div>
      </div>
      <div className="space-switch">
        <button
          className={"space-btn" + (state.space === "public" ? " active" : "")}
          onClick={() => switchSpace("public")}
        >
          公共星云
        </button>
        <button
          className={"space-btn" + (state.space === "mine" ? " active" : "")}
          onClick={() => switchSpace("mine")}
        >
          我的星云
        </button>
      </div>
      <button id="btn-jump" className="side-btn jump-btn" onClick={doJump}>
        <svg
          className="jump-btn-icon"
          viewBox="0 0 24 24"
          width="16"
          height="16"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z" />
          <path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z" />
          <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0" />
          <path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5" />
        </svg>
        星际跃迁
      </button>
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
          <input
            id="q"
            value={q}
            placeholder="搜索作家 / 作品…"
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onSearchKeyDown}
            onBlur={() => {
              // 点击外部关闭下拉(150ms 让点击项先触发,onMouseDown preventDefault 已阻止失焦)
              setTimeout(() => { setQResults([]); setQActive(-1); }, 150);
            }}
          />
          {qResults.length > 0 && (
            <ul id="q-results" style={{ display: "block" }}>
              {qResults.map((h, i) => (
                <li
                  key={h.id}
                  className={i === qActive ? "active" : undefined}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => chooseHit(h)}
                >
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
                onKeyDown={(e) => {
                  if (e.key === "Escape") setFromOpen(false);
                  if (e.key === "Enter") { e.preventDefault(); doPath(); }
                }}
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
                onKeyDown={(e) => {
                  if (e.key === "Escape") setToOpen(false);
                  if (e.key === "Enter") { e.preventDefault(); doPath(); }
                }}
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
          <div className="expand-stepper">
            <button
              type="button"
              className="expand-step"
              aria-label="减小扩散范围"
              onClick={() => stepExpand(-1)}
              disabled={state.expandHops <= 1}
            >◀</button>
            <input
              type="number"
              id="expand-input"
              min={1}
              max={state.expandMax}
              step={1}
              value={expandInput}
              onChange={(e) => onExpandInputChange(e.target.value)}
              onBlur={commitExpandInput}
              onKeyDown={(e) => {
                if (e.key === "Enter") e.currentTarget.blur();
              }}
            />
            <button
              type="button"
              className="expand-step"
              aria-label="增大扩散范围"
              onClick={() => stepExpand(1)}
              disabled={state.expandHops >= state.expandMax}
            >▶</button>
          </div>
        </div>
      </nav>
      <div className="sidebar-bottom">
        <label className="opt">
          <span>阅读状态</span>
          <select id="reading-filter" value={state.readingFilter} onChange={onReadingFilter}>
            <option value="all">全部</option>
            <option value="read">已读</option>
            <option value="reading">待读</option>
            <option value="unread">未读</option>
          </select>
        </label>
        <div className="opt-grid">
          <label className="opt">
            <input
              type="checkbox" id="show-authors" checked={state.showAuthors}
              onChange={onToggleAuthors}
            />
            <span>作家节点</span>
          </label>
          <label className="opt">
            <input
              type="checkbox" id="show-work-labels" checked={state.showWorkLabels}
              onChange={onToggleWorkLabels}
            />
            <span>作品名称</span>
          </label>
          <label className="opt">
            <input
              type="checkbox" id="hide-islands" checked={state.hideIslands}
              onChange={onToggleIslands}
            />
            <span>孤岛节点</span>
          </label>
        </div>
        <button
          id="btn-contribute"
          className="side-btn"
          onClick={() => {
            if (!state.user) {
              dispatch({ type: "SET_AUTH", open: true });
              dispatch({ type: "SET_TOAST", msg: "请先登录,再往你的星云添加数据", kind: "info" });
              return;
            }
            dispatch({ type: "SET_CONTRIBUTE", open: true });
          }}
        >
          点亮星空
        </button>
        {state.user?.role === "admin" && (
          <button
            id="btn-users"
            className="side-btn"
            title="用户管理(禁用/角色/星云可见性/VIP)"
            onClick={() => dispatch({ type: "SET_USER_ADMIN", open: true })}
          >
            用户管理
          </button>
        )}
        {state.user && (
          <button id="btn-admin" className="side-btn" onClick={() => dispatch({ type: "SET_ADMIN", open: true })}>
            数据管理
          </button>
        )}
        {state.user?.role === "admin" && (
          <button
            id="btn-ops"
            className="side-btn"
            title="运维管理(审计日志/快照备份恢复)"
            onClick={() => dispatch({ type: "SET_OPS", open: true })}
          >
            运维管理
          </button>
        )}
      </div>
    </>
  );
}
