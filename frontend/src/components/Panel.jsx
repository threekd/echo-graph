import React, { useEffect, useRef } from "react";
import { useApp } from "../store.jsx";
import { selectNode } from "../lib/graph.js";

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function AuthorPanel({ author, fullData }) {
  const works = fullData.nodes.filter((n) => n.type === "work" && n.author_id === author.id);
  const years = String(author.birthYear ?? "?") + " – " + String(author.deathYear ?? "?");
  const meta = [author.originalName || author.label_en, author.nationality, years]
    .filter(Boolean).join(" · ");
  return (
    <div className="panel-content-inner">
      <h2>{author.label}</h2>
      <div className="meta">{meta}</div>
      <h3>作品({works.length})</h3>
      <ul>
        {works.map((w) => (
          <li key={w.id} className="work-item" onClick={() => selectNode(w.id)}>
            <strong>{w.label}</strong> <small>({w.year || "?"} · {w.language || ""})</small>
          </li>
        ))}
      </ul>
      <p className="panel-hint">点击书籍可查看它的涟漪。</p>
    </div>
  );
}

function WorkPanel({ d }) {
  const w = d.work;
  const authorName = (d.authors && d.authors.length)
    ? d.authors.map((a) => a.name || a.originalName || "佚名").join("、")
    : (d.author ? (d.author.name || d.author.originalName || "佚名") : "佚名");
  return (
    <div className="panel-content-inner">
      <h2>{w.title}</h2>
      <div className="meta">{w.originalTitle || w.title_en} · {authorName} · {w.year || "?"} · {w.language}</div>
      {d.mentioned_by.length > 0 && (
        <>
          <h3>谁提及了这本书(回声来源)</h3>
          <ul>
            {d.mentioned_by.map((e, i) => (
              <li key={i}>
                <span className="tag-mention">提及</span>
                <strong>{e.source_title}</strong> <small>({e.source_author})</small>
                <div className="quote">{e.evidence}</div>
                {e.note ? <div className="quote dim">{e.note}</div> : null}
                {e.evidenceSource ? <div className="quote fainter">{e.evidenceSource}</div> : null}
              </li>
            ))}
          </ul>
        </>
      )}
      {d.mentions.length > 0 && (
        <>
          <h3>这本书提及了(涟漪扩散)</h3>
          <ul>
            {d.mentions.map((e, i) => (
              <li key={i}>
                <span className="tag-mention">提及</span>
                <strong>{e.target_title}</strong> <small>({e.target_author})</small>
                <div className="quote">{e.evidence}</div>
                {e.note ? <div className="quote dim">{e.note}</div> : null}
                {e.evidenceSource ? <div className="quote fainter">{e.evidenceSource}</div> : null}
              </li>
            ))}
          </ul>
        </>
      )}
      {d.mentioned_by.length === 0 && d.mentions.length === 0 && (
        <p className="no-path">这本书没有被其他书提及,也未提及别的书(孤岛星)。</p>
      )}
    </div>
  );
}

function PathPanel({ panel, fullData }) {
  const result = panel.result;
  const nodeById = {};
  fullData.nodes.forEach((n) => { nodeById[n.id] = n; });
  return (
    <div className="panel-content-inner">
      <h2>提及链(3D)</h2>
      <div className="meta">{panel.f} → {panel.t} · {result.nodes.length} 本书 / {result.edges.length} 次提及</div>
      {result.edges.map((e, i) => {
        const sn = nodeById[e.source];
        const tn = nodeById[e.target];
        return (
          <div key={i} className="path-step">
            <strong>{sn ? sn.label : e.source}</strong> → <strong>{tn ? tn.label : e.target}</strong>
            <div className="edge">提及 · {e.note || ""}</div>
            <div className="quote">{e.evidence || ""}</div>
            {e.evidenceSource ? <div className="quote fainter">{e.evidenceSource}</div> : null}
          </div>
        );
      })}
    </div>
  );
}

export default function Panel() {
  const { state } = useApp();
  const panel = state.panel;
  const hideTimer = useRef(null);

  const cancelHide = () => {
    if (hideTimer.current) {
      clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
  };

  const scheduleHide = () => {
    cancelHide();
    hideTimer.current = setTimeout(() => {
      const el = document.getElementById("panel");
      // 3 秒后鼠标仍不在面板上时才隐藏
      if (el && !el.matches(":hover")) el.classList.remove("show");
    }, 3000);
  };

  // 面板可见时:鼠标在面板范围内则保持;不在范围内 3 秒后自动隐藏
  useEffect(() => {
    const onMove = (e) => {
      const el = document.getElementById("panel");
      if (!el || !el.classList.contains("show")) return;
      const rect = el.getBoundingClientRect();
      const inside =
        e.clientX >= rect.left && e.clientX <= rect.right &&
        e.clientY >= rect.top && e.clientY <= rect.bottom;
      if (inside) cancelHide();
      else scheduleHide();
    };
    const onLeave = () => scheduleHide(); // 鼠标离开窗口时也进入倒计时
    window.addEventListener("mousemove", onMove);
    document.documentElement.addEventListener("mouseleave", onLeave);
    return () => {
      window.removeEventListener("mousemove", onMove);
      document.documentElement.removeEventListener("mouseleave", onLeave);
      cancelHide();
    };
  }, []);

  useEffect(() => {
    const el = document.getElementById("panel");
    if (el && panel.type !== "empty") {
      el.classList.add("show");
      scheduleHide(); // 展示时启动倒计时,鼠标移入面板会取消
    }
  }, [panel]);
  let content = null;
  if (panel.type === "empty") {
    content = (
      <div id="panel-empty">
        <p>点击任意星星,自动展开它的涟漪;</p>
        <p>右键拖拽旋转 · 左键拖拽平移 · 滚轮缩放。</p>
        <p>顶部可搜索作品、查找提及链。</p>
      </div>
    );
  } else if (panel.type === "author") {
    content = <AuthorPanel author={panel.author} fullData={state.fullData} />;
  } else if (panel.type === "work") {
    content = <WorkPanel d={panel.d} />;
  } else if (panel.type === "path") {
    content = <PathPanel panel={panel} fullData={state.fullData} />;
  }
  return (
    <>
      <div id="sidebar-zone-right"><span className="zone-icon">▶</span></div>
      <aside id="panel">
        <div id="panel-content">{content}</div>
      </aside>
    </>
  );
}
