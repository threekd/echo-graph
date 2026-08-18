import React, { useState, useEffect, useRef } from "react";
import { useApp } from "../store.jsx";
import { search } from "../lib/api.js";
import {
  renderMain, renderPath, selectNode, buildWorkLookups, expandRippleDebounced,
} from "../lib/graph.js";
import { getCameraState, toggleAuthorsInView } from "../lib/renderer.js";

export default function Sidebar() {
  const { state, dispatch } = useApp();
  const [q, setQ] = useState("");
  const [qResults, setQResults] = useState([]);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [expandText, setExpandText] = useState("1 级");
  const expandTimer = useRef(null);
  const lookups = useRef({ workLookup: {}, workById: {} });

  useEffect(() => {
    lookups.current = buildWorkLookups();
  }, [state.fullData]);

  useEffect(() => {
    if (!q.trim()) { setQResults([]); return; }
    const t = setTimeout(() => {
      search(q.trim()).then((r) => setQResults(r.hits || []));
    }, 200);
    return () => clearTimeout(t);
  }, [q]);

  const doPath = () => {
    const fid = lookups.current.workLookup[from.trim()];
    const tid = lookups.current.workLookup[to.trim()];
    if (!fid || !tid) {
      dispatch({ type: "SET_TOAST", msg: "请从下拉列表中选择两部作品" });
      return;
    }
    renderPath(fid, tid).then((result) => {
      if (!result) {
        dispatch({ type: "SET_TOAST", msg: "未找到提及链" });
        return;
      }
      dispatch({ type: "SET_PANEL", panel: { type: "path", result, f: from.trim(), t: to.trim() } });
    });
  };

  const onExpand = (hops) => {
    setExpandText(hops + " 级");
    dispatch({ type: "SET_EXPAND", value: hops });
    if (expandTimer.current) clearTimeout(expandTimer.current);
    expandTimer.current = setTimeout(() => expandRippleDebounced(hops), 400);
  };

  const shareLink = () => {
    const cam = getCameraState();
    const parts = ["v=main&cam=" + [cam.theta, cam.phi, cam.radius, cam.cx, cam.cy, cam.cz].map((x) => +x.toFixed(3)).join(",")];
    if (state.hideIslands) parts.push("islands=1");
    if (!state.showAuthors) parts.push("authors=0");
    const hash = parts.join("&");
    navigator.clipboard.writeText(location.origin + location.pathname + "#" + hash)
      .then(() => dispatch({ type: "SET_TOAST", msg: "分享链接已复制" }))
      .catch(() => dispatch({ type: "SET_TOAST", msg: "复制失败" }));
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
          if (!e.currentTarget.contains(e.relatedTarget)) e.currentTarget.classList.remove("show");
        }}
      >
        <div className="brand">
          <h1>The Echo Graph</h1>
          <span className="badge">回声图谱</span>
        </div>
        <nav>
          <div id="view-status">视图:{viewLabel(state.currentView)}</div>
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
            <datalist id="works-list">
              {state.fullData.nodes
                .filter((n) => n.type === "work")
                .map((w) => (
                  <option key={w.id} value={w.label + " - " + (w.author || "")} />
                ))}
            </datalist>
            <div className="path-fields">
              <div className="path-field">
                <input id="from" list="works-list" value={from} placeholder="起点作品" onChange={(e) => setFrom(e.target.value)} />
              </div>
              <button id="btn-swap" title="交换起终点" onClick={() => { setFrom(to); setTo(from); }}>⇅</button>
              <div className="path-field">
                <input id="to" list="works-list" value={to} placeholder="终点作品" onChange={(e) => setTo(e.target.value)} />
              </div>
            </div>
            <button id="btn-path" onClick={doPath}>寻找路径</button>
          </div>
          <button
            id="btn-back-main" className="side-btn"
            style={{ display: state.currentView === "main" ? "none" : "block" }}
            onClick={backMain}
          >
            返回全部图谱
          </button>
          <div id="expand-bar" style={{ display: state.currentView === "ripple" ? "flex" : "none" }}>
            <span className="expand-label">扩散范围</span>
            <input
              type="range" id="expand-range" min="1" max="8" step="1" value={state.expandHops}
              onChange={(e) => onExpand(parseInt(e.target.value, 10) || 1)}
            />
            <span id="expand-value">{expandText}</span>
          </div>
          <div className="tool-row">
            <button id="btn-share" onClick={shareLink}>分享链接</button>
            <button id="btn-export-png" onClick={exportPng}>导出图片</button>
          </div>
        </nav>
        <div className="sidebar-bottom">
          <label className="opt">
            <input
              type="checkbox" id="show-authors" checked={state.showAuthors}
              onChange={(e) => {
                dispatch({ type: "SET_SHOW_AUTHORS", value: e.target.checked });
                toggleAuthorsInView(!e.target.checked);
              }}
            />
            <span>显示作家节点</span>
          </label>
          <label className="opt">
            <input
              type="checkbox" id="hide-islands" checked={state.hideIslands}
              onChange={(e) => {
                const value = e.target.checked;
                dispatch({ type: "SET_HIDE_ISLANDS", value });
                if (state.currentView === "main") renderMain({ preserveCamera: true }, null, { hideIslands: value });
              }}
            />
            <span>隐藏孤岛星</span>
          </label>
          <button id="btn-admin" className="side-btn" onClick={() => dispatch({ type: "SET_ADMIN", open: true })}>数据管理</button>
        </div>
      </aside>
    </>
  );
}

function exportPng() {
  const canvas = document.querySelector("#graph canvas");
  if (!canvas) return;
  const cssRect = canvas.getBoundingClientRect();
  const labels = Array.from(document.querySelectorAll(".nodelabel"))
    .filter((elm) => getComputedStyle(elm).display !== "none")
    .map((elm) => {
      const rect = elm.getBoundingClientRect();
      return {
        text: elm.textContent,
        x: rect.left - cssRect.left + rect.width / 2,
        y: rect.top - cssRect.top + rect.height / 2,
        fontSize: parseFloat(getComputedStyle(elm).fontSize) || 11,
      };
    });
  const scale = 2;
  const out = document.createElement("canvas");
  out.width = cssRect.width * scale;
  out.height = cssRect.height * scale;
  const ctx = out.getContext("2d");
  ctx.scale(scale, scale);
  ctx.drawImage(canvas, 0, 0, cssRect.width, cssRect.height);
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  labels.forEach((lab) => {
    ctx.font = lab.fontSize + "px sans-serif";
    ctx.shadowColor = "rgba(0,0,0,0.95)";
    ctx.shadowBlur = 8;
    ctx.fillStyle = "#dbe9ff";
    ctx.fillText(lab.text, lab.x, lab.y);
  });
  const a = document.createElement("a");
  a.href = out.toDataURL("image/png");
  a.download = "echo-graph-" + Date.now() + ".png";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function viewLabel(view) {
  return view === "main" ? "全图谱" : view === "ripple" ? "涟漪" : view === "author" ? "作者" : "提及链";
}
