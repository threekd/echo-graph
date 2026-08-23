import { useCallback, useEffect, useState } from "react";
import { useApp } from "../store";
import type { AdminData, AdminTab } from "../lib/adminTypes";
import AdminTable from "./admin/AdminTable";
import AuditPanel from "./admin/AuditPanel";
import ContributionsPanel from "./admin/ContributionsPanel";
import SnapshotsPanel from "./admin/SnapshotsPanel";
import NodeFormModal, { type NodeKind } from "./admin/NodeFormModal";
import { refreshSpaceGraph } from "../lib/graph";
import {
  authorLabelOf,
  workLabel,
} from "./admin/pickers";
import { authorDisplayNames, edgeDisplayLabel } from "./admin/query";

// 从 URL 中移除 admin 入口参数/片段,恢复到普通页面状态
function stripAdminFromUrl(): void {
  try {
    const url = new URL(window.location.href);
    url.searchParams.delete("admin");
    if (url.hash.indexOf("admin") !== -1) url.hash = "#v=main";
    history.replaceState(null, "", url.toString());
  } catch { /* ignore */ }
}

const KINDS: { key: AdminTab; label: string }[] = [
  { key: "authors", label: "作者" },
  { key: "works", label: "作品" },
  { key: "edges", label: "涟漪" },
  { key: "contributions", label: "贡献" },
  { key: "audit", label: "日志" },
  { key: "snapshots", label: "快照" },
];

// 作者/作品表默认按修改时间从新到旧排序(updatedAt 为 UTC ISO 字符串,字典序即时间序);其余 Tab 不默认排序
function defaultSortFor(k: AdminTab): { key: string; dir: 1 | -1 } | null {
  return k === "authors" || k === "works" ? { key: "updatedAt", dir: -1 } : null;
}

function colsFor(isAdmin: boolean): Record<AdminTab, { key: string; label: string }[]> {
  const reviewCol = (label: string) => ({ key: "reviewStatus", label });
  const visibilityCol = { key: "visibility", label: "可见性" };
  return {
    authors: isAdmin
      ? [
          { key: "Name_CN", label: "中文名" },
          { key: "originalName", label: "原文名" },
          { key: "nationality", label: "国家" },
          reviewCol("审核状态"),
        ]
      : [
          { key: "Name_CN", label: "中文名" },
          { key: "originalName", label: "原文名" },
          { key: "nationality", label: "国家" },
          visibilityCol,
        ],
    works: isAdmin
      ? [
          { key: "Title_CN", label: "中文名" },
          { key: "originalTitle", label: "原著标题" },
          { key: "author_id", label: "作者" },
          { key: "publicationYear", label: "年份" },
          reviewCol("审核状态"),
        ]
      : [
          { key: "Title_CN", label: "中文名" },
          { key: "originalTitle", label: "原著标题" },
          { key: "author_id", label: "作者" },
          { key: "publicationYear", label: "年份" },
          { key: "recommendation", label: "评分" },
          visibilityCol,
        ],
    edges: isAdmin
      ? [
          { key: "source_work_id", label: "源作品" },
          { key: "target_work_id", label: "目标作品" },
          reviewCol("审核"),
          { key: "evidenceSource", label: "出处" },
        ]
      : [
          { key: "source_work_id", label: "源作品" },
          { key: "target_work_id", label: "目标作品" },
          { key: "evidenceSource", label: "出处" },
        ],
    contributions: [],
    audit: [],
    snapshots: [],
  };
}

function contributionStatusLabel(s: string): string {
  return s === "approved" ? "已通过" : s === "rejected" ? "已驳回" : "待审核";
}

export default function Admin() {
  const { state, dispatch } = useApp();
  // 数据管理对所有登录用户开放:非 admin 管理自己的空间(/api/me),
  // admin 管理公共星云(/api/admin,即其名下数据);贡献/日志/快照仅 admin。
  const isAdmin = state.user?.role === "admin";
  const apiBase = isAdmin ? "/api/admin" : "/api/me";
  const tabs = isAdmin ? KINDS : KINDS.filter((k) => !["contributions", "audit", "snapshots"].includes(k.key));
  const [kind, setKind] = useState<AdminTab>("authors");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const [contribs, setContribs] = useState<any[]>([]);
  const [contribsLoading, setContribsLoading] = useState(false);
  const [contribCount, setContribCount] = useState(0);
  const [viewContrib, setViewContrib] = useState<any>(null);
  const [confirmState, setConfirmState] = useState<{
    title: string;
    message: string;
    danger?: boolean;
    onConfirm: () => void;
  } | null>(null);
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(() => defaultSortFor("authors"));
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [textFilters, setTextFilters] = useState<Record<string, string>>({});
  const [warnings, setWarnings] = useState<any>(null);
  const [modal, setModal] = useState<any>(null); // { mode: "add" | "edit", row: {} }

  // 非 admin 用户的管理面板只面向自己的星云,给出明确提示
  useEffect(() => {
    setStatus(isAdmin ? "" : "管理你的星云数据(仅本人可见)");
  }, [isAdmin]);
  const authFetch = useCallback((url: string, options: RequestInit = {}) => {
    // 会话凭据由 httpOnly Cookie 自动携带,无需手动附加
    return fetch(url, options);
  }, []);

  const handleAuthError = (r: Response): boolean => {
    if (r.status === 401 || r.status === 403) {
      setStatus("需要管理员权限(请以管理员账号登录)");
      return true;
    }
    return false;
  };

  // 关闭管理页;同时清理 URL 中的 admin 入口参数/片段
  const closeAdmin = () => {
    stripAdminFromUrl();
    dispatch({ type: "SET_ADMIN", open: false });
  };

  const load = useCallback(() => {
    setLoading(true);
    authFetch(apiBase + "/data")
      .then((r) => {
        if (!r.ok) {
          handleAuthError(r);
          setLoading(false);
          return null;
        }
        return r.json();
      })
      .then((d) => {
        if (d) {
          setData(d);
          setWarnings(d.warnings || null);
          setLoading(false);
        }
      })
      .catch((e) => { setStatus("加载失败: " + e.message); setLoading(false); });
  }, [authFetch, apiBase]);

  useEffect(() => { load(); }, [load]);

  // 贡献收件箱:按状态拉取列表(供"贡献"Tab 使用)
  const loadContribs = useCallback(() => {
    setContribsLoading(true);
    authFetch("/api/admin/contributions?limit=500")
      .then((r) => r.json())
      .then((d) => {
        const items = d.items || [];
        setContribs(items);
        // Tab 角标保持"待审核"数(筛选/排序由表格内完成)
        setContribCount(items.filter((c: any) => c.status === "pending").length);
        setContribsLoading(false);
      })
      .catch((e) => { setStatus("加载贡献失败: " + e.message); setContribsLoading(false); });
  }, [authFetch]);

  useEffect(() => {
    if (isAdmin && kind === "contributions") loadContribs();
  }, [isAdmin, kind, loadContribs]);

  // 打开管理页即加载待审核数,让"贡献"Tab 角标未切换过去时也显示正确数字
  useEffect(() => {
    if (isAdmin) loadContribs();
  }, [isAdmin, loadContribs]);

  if (!state.adminOpen) return null;

  const allRows: any[] = data ? data[kind] || [] : [];
  const cols = colsFor(isAdmin)[kind];
  const counts = data ? data.counts || {} : {};

  // Tab 角标计数:贡献/日志为特殊 Tab,避免对不存在的 data[k] 取值
  const tabCount = (k: AdminTab): string => {
    if (k === "contributions") return String(contribCount);
    if (k === "audit" || k === "snapshots") return "";
    return counts[k] != null ? String(counts[k]) : (data ? String((data[k] || []).length) : "");
  };

  // 每类数据的可筛选列:select 为精确下拉,text 为按列搜索框
  const filterCols = (isAdmin
    ? {
        authors: [
          { key: "reviewStatus", type: "select" as const },
          { key: "nationality", type: "select" as const },
          { key: "Name_CN", type: "text" as const },
          { key: "originalName", type: "text" as const },
        ],
        works: [
          { key: "reviewStatus", type: "select" as const },
          { key: "genre", type: "select" as const },
          { key: "language", type: "select" as const },
          { key: "Title_CN", type: "text" as const },
          { key: "originalTitle", type: "text" as const },
          { key: "author_id", type: "text" as const },
          { key: "publicationYear", type: "text" as const },
        ],
        edges: [
          { key: "reviewStatus", type: "select" as const },
          { key: "source_work_id", type: "text" as const },
          { key: "target_work_id", type: "text" as const },
          { key: "evidenceSource", type: "text" as const },
        ],
      }
    : {
        authors: [
          { key: "visibility", type: "select" as const },
          { key: "nationality", type: "select" as const },
          { key: "Name_CN", type: "text" as const },
          { key: "originalName", type: "text" as const },
        ],
        works: [
          { key: "visibility", type: "select" as const },
          { key: "recommendation", type: "select" as const },
          { key: "genre", type: "select" as const },
          { key: "language", type: "select" as const },
          { key: "Title_CN", type: "text" as const },
          { key: "originalTitle", type: "text" as const },
          { key: "author_id", type: "text" as const },
          { key: "publicationYear", type: "text" as const },
        ],
        edges: [
          { key: "source_work_id", type: "text" as const },
          { key: "target_work_id", type: "text" as const },
          { key: "evidenceSource", type: "text" as const },
        ],
      }) as Record<AdminTab, { key: string; type: "select" | "text" }[]>;
  const uniqueValues = (key: string): string[] =>
    Array.from(new Set(allRows.map((r) => String(r[key] || "")).filter(Boolean))).sort((a, b) => a.localeCompare(b));

  const toggleSort = (key: string) => {
    setSort((prev) => {
      if (prev && prev.key === key) return prev.dir === 1 ? { key, dir: -1 } : null;
      return { key, dir: 1 };
    });
  };

  const switchKind = (k: AdminTab) => {
    setKind(k);
    setModal(null);
    setFilters({});
    setTextFilters({});
    setSort(defaultSortFor(k));
  };

  const openAdd = () => {
    setModal({ mode: "add", row: {} });
  };

  const openEdit = (row: any) => {
    setModal({ mode: "edit", row });
  };

  // 乐观更新:成功后直接改本地 data,不再整页重拉(仅刷新同步状态)
  const applyLocal = (updater: (prev: AdminData) => AdminData) => {
    if (data) setData(updater(data));
  };

  // 数据写入后刷新星云图(仅当管理空间与当前浏览空间一致时才有意义:
  // admin 管理公共星云,其「我的星云」同源;普通用户管理自己的星云)
  const refreshGraphAfterWrite = () => {
    const relevant = isAdmin
      ? state.space === "public" || state.space === "mine"
      : state.space === "mine";
    if (relevant) refreshSpaceGraph();
  };

  const doDelete = (row: any) => {
    const id = row.id;
    setConfirmState({
      title: "确认删除",
      message: `确认删除「${rowLabel(row)}」?(软删除,可恢复,关联的作品/涟漪将一并软删除)`,
      danger: true,
      onConfirm: () => {
        authFetch(apiBase + "/" + kind + "/" + encodeURIComponent(id), { method: "DELETE" })
          .then((r) => r.json())
          .then((d) => {
            const cascade = d.cascade || {};
            const parts: string[] = [];
            if (cascade.works && cascade.works.length) parts.push(cascade.works.length + " 部作品");
            if (cascade.edges && cascade.edges.length) parts.push(cascade.edges.length + " 条涟漪");
            setStatus(
              d.ok
                ? `已软删除「${rowLabel(row)}」${parts.length ? ",连带 " + parts.join(" / ") : ""}`
                : (d.detail || "删除失败")
            );
            if (d.ok) {
              setModal(null); // 从编辑弹窗删除后关闭弹窗
              const key = kind as "authors" | "works" | "edges";
              applyLocal((prev) => ({
                ...prev,
                [key]: (prev[key] || []).map((r: any) =>
                  r.id === id ? { ...r, deletedAt: d.deletedAt } : r
                ),
              }));
              refreshGraphAfterWrite();
            }
          })
          .catch((e) => setStatus("删除失败: " + e.message));
      },
    });
  };

  const doRestore = (id: string) => {
    const row = allRows.find((r) => r.id === id);
    if (!row) return;
    authFetch(apiBase + "/" + kind + "/" + encodeURIComponent(id) + "/restore", { method: "POST" })
      .then((r) => r.json())
      .then((d) => {
        const cascade = d.cascade || {};
        const parts: string[] = [];
        if (cascade.works && cascade.works.length) parts.push(cascade.works.length + " 部作品");
        if (cascade.edges && cascade.edges.length) parts.push(cascade.edges.length + " 条涟漪");
        setStatus(
          d.ok
            ? `已恢复「${rowLabel(row)}」${parts.length ? ",连带恢复 " + parts.join(" / ") : ""}`
            : (d.detail || "恢复失败")
        );
        if (d.ok) {
          const key = kind as "authors" | "works" | "edges";
          applyLocal((prev) => ({
            ...prev,
            [key]: (prev[key] || []).map((r: any) =>
              r.id === id ? { ...r, deletedAt: null } : r
            ),
          }));
          refreshGraphAfterWrite();
        }
      })
      .catch((e) => setStatus("恢复失败: " + e.message));
  };

  const worksList = data ? data.works || [] : [];
  const authorsList = data ? data.authors || [] : [];
  const worksById: Record<string, any> = {};
  const authorsById: Record<string, any> = {};
  worksList.forEach((w: any) => { worksById[w.id] = w; });
  authorsList.forEach((a: any) => { authorsById[a.id] = a; });

  // 行显示名(删除确认/状态提示用):作者名 / 作品标题 / 涟漪 A → B
  const rowLabel = (row: any): string => {
    if (kind === "authors") return authorLabelOf(row);
    if (kind === "works") return workLabel(row);
    return edgeDisplayLabel(row, worksById, workLabel);
  };

  // 单元格显示值(与表格渲染一致,排序/筛选共用)
  const cellValue = (r: any, key: string): string => {
    if (kind === "edges" && (key === "source_work_id" || key === "target_work_id")) {
      const w = worksById[r[key]];
      return w ? workLabel(w) : String(r[key] ?? "");
    }
    if (kind === "works" && key === "author_id") {
      return authorDisplayNames(r, authorsById, authorLabelOf);
    }
    if (key === "visibility") {
      return r[key] === "private" ? "隐藏" : "公开";
    }
    if (key === "recommendation") {
      return r[key] === "recommend" ? "推荐" : r[key] === "not_recommend" ? "不推荐" : "";
    }
    const v = r[key];
    return v == null ? "" : String(v);
  };

  return (
    <div id="admin-overlay">
      <div className="admin-shell">
        <div className="admin-head">
          <div className="admin-head-left">
            <h2 className="admin-title">数据管理</h2>
            <div className="admin-tabs">
              {tabs.map((k) => (
                <button
                  key={k.key}
                  className={"admin-tab" + (kind === k.key ? " active" : "")}
                  data-kind={k.key}
                  onClick={() => switchKind(k.key)}
                >
                  {k.label} <span className="cnt">{tabCount(k.key)}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="admin-actions">
            {kind !== "contributions" && kind !== "audit" && kind !== "snapshots" && <button onClick={openAdd}>＋ 新增</button>}
            <button id="admin-close" onClick={closeAdmin}>关闭</button>
          </div>
        </div>
        <div id="admin-status">{status}</div>
        {warnings && Boolean(warnings.duplicateAuthorNames?.length || warnings.duplicateWorkTitles?.length || warnings.duplicateEdgePairs?.length) && (
          <div id="admin-warnings">
            ⚠ 重复提醒:
            {warnings.duplicateAuthorNames?.length ? " 作者名:" + warnings.duplicateAuthorNames.join("、") : ""}
            {warnings.duplicateWorkTitles?.length ? " 作品标题:" + warnings.duplicateWorkTitles.join("、") : ""}
            {warnings.duplicateEdgePairs?.length ? " 涟漪对:" + warnings.duplicateEdgePairs.join("、") : ""}
          </div>
        )}
        {confirmState && (
          <div id="auth-modal">
            <div className="auth-modal-card">
              <h3>{confirmState.title}</h3>
              <p>{confirmState.message}</p>
              <div className="admin-modal-actions">
                <button
                  className={confirmState.danger ? "del" : undefined}
                  onClick={() => {
                    const run = confirmState.onConfirm;
                    setConfirmState(null);
                    run();
                  }}
                >
                  确认
                </button>
                <button onClick={() => setConfirmState(null)}>取消</button>
              </div>
            </div>
          </div>
        )}
        <div className="admin-body">
          {kind === "contributions" ? (
            <ContributionsPanel
              items={contribs}
              loading={contribsLoading}
              sort={sort}
              filters={filters}
              textFilters={textFilters}
              onSort={toggleSort}
              onFilter={(k, v) => setFilters((f) => ({ ...f, [k]: v }))}
              onTextFilter={(k, v) => setTextFilters((f) => ({ ...f, [k]: v }))}
              onView={setViewContrib}
            />
          ) : kind === "audit" ? (
            <AuditPanel
              authFetch={authFetch}
              sort={sort}
              filters={filters}
              textFilters={textFilters}
              onSort={toggleSort}
              onFilter={(k, v) => setFilters((f) => ({ ...f, [k]: v }))}
              onTextFilter={(k, v) => setTextFilters((f) => ({ ...f, [k]: v }))}
            />
          ) : kind === "snapshots" ? (
            <SnapshotsPanel authFetch={authFetch} />
          ) : loading ? <p>加载中…</p> : (
            <AdminTable
              kind={kind}
              cols={cols}
              rows={allRows}
              filterCols={filterCols[kind]}
              filters={filters}
              textFilters={textFilters}
              sort={sort}
              cellValue={cellValue}
              uniqueValues={uniqueValues}
              onSort={toggleSort}
              onFilter={(k, v) => setFilters((f) => ({ ...f, [k]: v }))}
              onTextFilter={(k, v) => setTextFilters((f) => ({ ...f, [k]: v }))}
              renderActions={(r) =>
                r.deletedAt
                  ? <button onClick={() => doRestore(r.id)}>恢复</button>
                  : <button onClick={() => openEdit(r)}>编辑</button>
              }
            />
          )}
        </div>
        {viewContrib && (
          <div id="admin-modal" style={{ display: "flex" }}>
            <div className="admin-modal-card">
              <h3>贡献详情</h3>
              <div id="admin-form">
                <label>
                  <span>源作品(提及方)</span>
                  <input readOnly value={viewContrib.source_work || ""} />
                </label>
                <label>
                  <span>源作品作者</span>
                  <input readOnly value={viewContrib.source_author || ""} />
                </label>
                <label>
                  <span>目标作品(被提及方)</span>
                  <input readOnly value={viewContrib.target_work || ""} />
                </label>
                <label>
                  <span>目标作品作者</span>
                  <input readOnly value={viewContrib.target_author || ""} />
                </label>
                <label className="full">
                  <span>原文片段</span>
                  <textarea readOnly value={viewContrib.evidence || ""} />
                </label>
                <label>
                  <span>出处(章节/页码/译本)</span>
                  <input readOnly value={viewContrib.evidence_source || ""} />
                </label>
                <label className="full">
                  <span>备注</span>
                  <textarea readOnly value={viewContrib.note || ""} />
                </label>
                <label>
                  <span>联系方式</span>
                  <input readOnly value={viewContrib.contact || ""} />
                </label>
                <label>
                  <span>提交时间</span>
                  <input readOnly value={viewContrib.created_at || ""} />
                </label>
                <label>
                  <span>审核状态</span>
                  <input readOnly value={contributionStatusLabel(viewContrib.status || "")} />
                </label>
              </div>
              <div className="admin-modal-actions">
                <button onClick={() => setViewContrib(null)}>关闭</button>
              </div>
            </div>
          </div>
        )}
      </div>

      {modal && (
        <NodeFormModal
          kind={kind as NodeKind}
          mode={modal.mode}
          initial={modal.row}
          apiBase={apiBase}
          authorsList={authorsList}
          worksList={worksList}
          edgesList={data?.edges || []}
          isAdmin={isAdmin}
          onClose={() => setModal(null)}
          onAuthorAdded={(row) => {
            applyLocal((prev) => ({ ...prev, authors: [...(prev.authors || []), row] }));
            refreshGraphAfterWrite();
          }}
          onReload={() => {
            setModal(null);
            load();
          }}
          onSaved={(row) => {
            setModal(null);
            setStatus(modal.mode === "edit" ? "已更新" : "已新增");
            const key = kind as "authors" | "works" | "edges";
            applyLocal((prev) => {
              const list = (prev[key] || []) as any[];
              if (modal.mode === "edit") {
                return { ...prev, [key]: list.map((r: any) => (r.id === row.id ? row : r)) };
              }
              return { ...prev, [key]: [...list, row] };
            });
            refreshGraphAfterWrite();
          }}
          onDelete={modal.mode === "edit" ? () => doDelete(modal.row) : undefined}
        />
      )}
    </div>
  );
}
