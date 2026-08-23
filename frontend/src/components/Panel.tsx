import { useCallback, useEffect, useRef, useState } from "react";
import { useApp, type GraphData } from "../store";
import { selectNode } from "../lib/graph";
import { workAuthorIds } from "../lib/graphData";
import { isMobileLayout } from "../lib/mobileGestures";
import { followRelation, followUser, spaceUserId, unfollowUser } from "../lib/api";
import PinButton from "./PinButton";
import iso3166 from "../lib/iso3166-1.json";
import GuideItems from "./GuideItems";

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

// 书签:当前所选作品的个人评分与评价
function BookmarkPanel({ work }: { work: any }) {
  if (!work) {
    return (
      <div className="panel-content-inner">
        <h2>书签</h2>
        <p className="no-path">请先点击一部作品,查看它的评分与评价。</p>
      </div>
    );
  }
  const rec = work.recommendation;
  return (
    <div className="panel-content-inner">
      <h2>书签</h2>
      <div className="meta">{work.title}</div>
      <h3>评分</h3>
      <p className={rec === "recommend" || rec === "not_recommend" ? "meta" : "no-path"}>
        {rec === "recommend" ? "推荐" : rec === "not_recommend" ? "不推荐" : "未评分"}
      </p>
      <h3>评价</h3>
      {work.review ? (
        <p className="quote">{work.review}</p>
      ) : (
        <p className="no-path">暂无评价。</p>
      )}
    </div>
  );
}

// 关注按钮:浏览他人星云时在「个人资料」Tab 显示(不可关注自己)
function FollowButton({ ownerId }: { ownerId: string }) {
  const { dispatch } = useApp();
  const [following, setFollowing] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    followRelation(ownerId)
      .then((r) => { if (!cancelled) setFollowing(r.following); })
      .catch(() => { /* 关系查询失败不阻塞页面 */ });
    return () => { cancelled = true; };
  }, [ownerId]);

  const toggle = () => {
    if (busy) return;
    setBusy(true);
    const req = following ? unfollowUser(ownerId) : followUser(ownerId);
    req
      .then(() => {
        setFollowing(!following);
        dispatch({
          type: "SET_TOAST",
          msg: following ? "已取消关注" : "已关注",
          kind: "success",
        });
      })
      .catch((e) => dispatch({ type: "SET_TOAST", msg: e.message || "操作失败", kind: "error" }))
      .finally(() => setBusy(false));
  };

  return (
    <button
      className={"side-btn follow-btn" + (following ? " following" : "")}
      onClick={toggle}
      disabled={busy}
    >
      {busy ? "请稍候…" : following ? "已关注 · 点击取关" : "＋ 关注"}
    </button>
  );
}

// 个人资料:当前星云所有者的昵称与简介;浏览他人星云时提供关注入口
function OwnerProfilePanel({
  profile,
  ownerId,
  isSelf,
}: {
  profile: { username?: string; nickname?: string | null; bio?: string | null } | null;
  ownerId: string | null;
  isSelf: boolean;
}) {
  const name =
    (profile?.nickname || "").trim() || (profile?.username || "").trim() || "匿名星云";
  return (
    <div className="panel-content-inner">
      <h2>个人资料</h2>
      <div className="meta">{name}</div>
      {ownerId && !isSelf && <FollowButton ownerId={ownerId} />}
      <h3>简介</h3>
      {profile?.bio ? (
        <p className="quote">{profile.bio}</p>
      ) : (
        <p className="no-path">TA 还没有填写简介。</p>
      )}
    </div>
  );
}

export default function Panel() {
  const { state, dispatch } = useApp();
  const panel = state.panel;
  // 右侧详情栏功能 Tab:ripple = 当前视图内容;bookmarks = 书签(评分/评价);profile = 星云所有者资料
  const [tab, setTab] = useState<"ripple" | "bookmarks" | "profile">("ripple");
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
    if (isMobileLayout() || state.pinRight) return; // 钉住:不自动隐藏
    cancelHide();
    hideTimer.current = setTimeout(() => {
      const el = document.getElementById("panel");
      // 3 秒后鼠标仍不在面板上时才隐藏
      if (el && !el.matches(":hover")) {
        el.classList.remove("show");
        wasInsideRef.current = false;
      }
    }, 3000);
  }, [cancelHide, state.pinRight]);

  const hidePanel = useCallback(() => {
    if (state.pinRight) return; // 钉住:不随移出/计时隐藏
    cancelHide();
    const el = document.getElementById("panel");
    if (el) el.classList.remove("show");
    wasInsideRef.current = false;
  }, [cancelHide, state.pinRight]);

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
  }, [cancelHide, hidePanel, scheduleHide, state.pinRight]);

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
        if (!state.pinRight) {
          el.classList.remove("show"); // 内容置空时收起(手机端点击节点不弹详情栏)
        }
        wasInsideRef.current = false;
      }
    }
  }, [panel, scheduleHide, state.pinRight]);

  // 钉住右侧详情栏:钉住后不再随移出/计时自动隐藏
  const togglePinRight = () => {
    const next = !state.pinRight;
    dispatch({ type: "SET_PIN_RIGHT", value: next });
    try {
      localStorage.setItem("echo_graph_pin_right", next ? "1" : "");
    } catch {
      /* ignore */
    }
    const el = document.getElementById("panel");
    if (el) {
      if (next) el.classList.add("show");
      // 取消钉住不立即收起,下一次移出/计时按原逻辑隐藏
    }
  };
  let content = null;
  if (panel.type === "empty") {
    content = (
      <div id="panel-empty">
        {/* 主视图详情栏空状态:操作说明按设备定制,内容与新手导引同源 */}
        <GuideItems mobile={isMobileLayout()} />
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
        <PinButton
          id="btn-pin-right"
          pinned={state.pinRight}
          title={state.pinRight ? "取消钉住" : "钉住"}
          onToggle={togglePinRight}
        />
        <div className="sidebar-tabs" role="tablist" aria-label="详情栏功能">
          <button
            id="tab-ripple"
            className={"sidebar-tab" + (tab === "ripple" ? " active" : "")}
            role="tab"
            aria-selected={tab === "ripple"}
            title="涟漪"
            onClick={() => setTab("ripple")}
          >
            <svg
              className="sidebar-tab-svg"
              viewBox="0 0 24 24"
              width="16"
              height="16"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="2.2" fill="currentColor" stroke="none" />
              <circle cx="12" cy="12" r="6" />
              <circle cx="12" cy="12" r="10" />
            </svg>
            <span className="sidebar-tab-label">涟漪</span>
          </button>
          <button
            id="tab-bookmarks"
            className={"sidebar-tab" + (tab === "bookmarks" ? " active" : "")}
            role="tab"
            aria-selected={tab === "bookmarks"}
            title="书签"
            onClick={() => setTab("bookmarks")}
          >
            <svg className="sidebar-tab-svg" viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">
              <path d="M17 3H7c-1.1 0-1.99.9-1.99 2L5 21l7-3 7 3V5c0-1.1-.9-2-2-2z" />
            </svg>
            <span className="sidebar-tab-label">书签</span>
          </button>
          <button
            id="tab-profile"
            className={"sidebar-tab" + (tab === "profile" ? " active" : "")}
            role="tab"
            aria-selected={tab === "profile"}
            title="星云所有者的个人资料"
            onClick={() => setTab("profile")}
          >
            <svg className="sidebar-tab-svg" viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">
              <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z" />
            </svg>
            <span className="sidebar-tab-label">书友</span>
          </button>
        </div>
        <div id="panel-content">
          {tab === "ripple" ? (
            content
          ) : tab === "bookmarks" ? (
            <BookmarkPanel work={panel.type === "work" ? panel.d?.work : null} />
          ) : (
            <OwnerProfilePanel
              profile={state.spaceProfile}
              ownerId={spaceUserId(state.space)}
              isSelf={!!state.user && spaceUserId(state.space) === state.user.id}
            />
          )}
        </div>
      </aside>
    </>
  );
}
