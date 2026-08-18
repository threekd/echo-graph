import React, { useEffect } from "react";
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
  const meta = [author.originalName || author.label_en, author.nationality, years, author.primaryLanguage ? "语言 " + author.primaryLanguage : ""]
    .filter(Boolean).join(" · ");
  return (
    <div className="panel-content-inner">
      <h2>{author.label}</h2>
      <div className="meta">{meta}</div>
      {author.bio ? <p className="panel-bio">{author.bio}</p> : null}
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
  const w = d.work, a = d.author;
  return (
    <div className="panel-content-inner">
      <h2>{w.title}</h2>
      <div className="meta">{w.originalTitle || w.title_en} · {a.name} · {w.year || "?"} · {w.language}</div>
      {w.summary ? <p className="panel-bio">{w.summary}</p> : null}
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
  useEffect(() => {
    const el = document.getElementById("panel");
    if (el && panel.type !== "empty") el.classList.add("show");
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
  } else if (panel.type === "noPath") {
    content = <p className="no-path">未找到「{panel.f} → {panel.t}」的提及链。</p>;
  }
  return (
    <>
      <div id="sidebar-zone-right"><span className="zone-icon">▶</span></div>
      <aside
        id="panel"
        onMouseLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget)) e.currentTarget.classList.remove("show");
        }}
      >
        <div id="panel-content">{content}</div>
      </aside>
    </>
  );
}
