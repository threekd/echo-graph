import { useCallback, useEffect, useRef } from "react";
import { useApp, type GraphData } from "../store";
import { selectNode } from "../lib/graph";
import { workAuthorIds } from "../lib/graphData";
import { isMobileLayout } from "../lib/mobileGestures";
import iso3166 from "../lib/iso3166-1.json";

const iso3166Map = iso3166 as Record<string, string>;

function AuthorPanel({ author, fullData }: { author: any; fullData: GraphData }) {
  const works = fullData.nodes.filter((n) => n.type === "work" && workAuthorIds(n).includes(author.id));
  const years = String(author.birthYear ?? "?") + " – " + String(author.deathYear ?? "?");
  const nationality = author.nationality ? (iso3166Map[author.nationality] || author.nationality) : "";
  const meta = [author.originalName || author.label_en, nationality, years]
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

function WorkPanel({ d }: { d: any }) {
  const w = d.work;
  const authorName = (d.authors && d.authors.length)
    ? d.authors.map((a: any) => a.name || a.originalName || "佚名").join("、")
    : (d.author ? (d.author.name || d.author.originalName || "佚名") : "佚名");
  return (
    <div className="panel-content-inner">
      <h2>{w.title}</h2>
      <div className="meta">{w.originalTitle || w.title_en} · {authorName} · {w.year || "?"} · {w.language}</div>
      {d.mentioned_by.length > 0 && (
        <>
          <h3>回声来源</h3>
          <ul>
            {d.mentioned_by.map((e: any, i: number) => (
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
          <h3>涟漪扩散</h3>
          <ul>
            {d.mentions.map((e: any, i: number) => (
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
        <p className="no-path">漂浮中。</p>
      )}
    </div>
  );
}

function PathPanel({ panel, fullData }: { panel: any; fullData: GraphData }) {
  const result = panel.result;
  const nodeById: Record<string, any> = {};
  fullData.nodes.forEach((n) => { nodeById[n.id] = n; });
  return (
    <div className="panel-content-inner">
      <h2>提及链(3D)</h2>
      <div className="meta">{panel.f} → {panel.t} · {result.nodes.length} 本书 / {result.edges.length} 次提及</div>
      {result.edges.map((e: any, i: number) => {
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
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wasInsideRef = useRef(false); // 鼠标是否曾经进入过面板(进过再移出 -> 立即隐藏)

  const cancelHide = useCallback(() => {
    if (hideTimer.current) {
      clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
  }, []);

  const scheduleHide = useCallback(() => {
    // 触屏没有 hover:移动端保持打开,由栏外点击收起,不做自动隐藏
    if (isMobileLayout()) return;
    cancelHide();
    hideTimer.current = setTimeout(() => {
      const el = document.getElementById("panel");
      // 3 秒后鼠标仍不在面板上时才隐藏
      if (el && !el.matches(":hover")) {
        el.classList.remove("show");
        wasInsideRef.current = false;
      }
    }, 3000);
  }, [cancelHide]);

  const hidePanel = useCallback(() => {
    cancelHide();
    const el = document.getElementById("panel");
    if (el) el.classList.remove("show");
    wasInsideRef.current = false;
  }, [cancelHide]);

  // 面板可见时:鼠标在面板范围内则保持;不在范围内 3 秒后自动隐藏
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (isMobileLayout()) return; // 移动端不依赖鼠标位置自动隐藏
      const el = document.getElementById("panel");
      if (!el || !el.classList.contains("show")) return;
      const rect = el.getBoundingClientRect();
      const inside =
        e.clientX >= rect.left && e.clientX <= rect.right &&
        e.clientY >= rect.top && e.clientY <= rect.bottom;
      if (inside) {
        wasInsideRef.current = true;
        cancelHide();
      } else if (wasInsideRef.current) {
        hidePanel(); // 从面板内移出:立即隐藏
      } else {
        scheduleHide(); // 从未进入面板:维持 3 秒倒计时
      }
    };
    const onLeave = () => {
      if (wasInsideRef.current) hidePanel();
      else scheduleHide(); // 鼠标离开窗口时也进入倒计时
    };
    window.addEventListener("mousemove", onMove);
    document.documentElement.addEventListener("mouseleave", onLeave);
    return () => {
      window.removeEventListener("mousemove", onMove);
      document.documentElement.removeEventListener("mouseleave", onLeave);
      cancelHide();
    };
  }, [cancelHide, hidePanel, scheduleHide]);

  useEffect(() => {
    const el = document.getElementById("panel");
    if (el) {
      if (panel.type !== "empty") {
        if (!isMobileLayout()) {
          el.classList.add("show");
          scheduleHide(); // 桌面:展示时启动倒计时,鼠标移入面板会取消
        }
        // 手机端:内容保留但不自动呼出,由底部右侧上划打开
      } else {
        el.classList.remove("show"); // 内容置空时收起(手机端点击节点不弹详情栏)
        wasInsideRef.current = false;
      }
    }
  }, [panel, scheduleHide]);
  let content = null;
  if (panel.type === "empty") {
    content = (
      <div id="panel-empty">
        <p>点击任意星星,自动展开它的涟漪;</p>
        <p>桌面:右键拖拽旋转 · 左键拖拽平移 · 滚轮缩放。</p>
        <p>手机:单指平移 · 双指旋转 / 缩放。</p>
        <p>手机:点击节点进入层级后,右侧上划可查看该节点详情。</p>
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
