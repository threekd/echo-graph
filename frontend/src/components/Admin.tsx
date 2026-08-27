import { useCallback, useEffect, useState } from "react";
import { useApp } from "../store";
import type {
  AdminData, AdminKind, AdminRow, AdminTab, AuthorRow, EdgeRow, WorkRow,
} from "../lib/adminTypes";
import AdminTable from "./admin/AdminTable";
import LlmDraftsPanel from "./admin/LlmDraftsPanel";
import NodeFormModal, { type NodeKind } from "./admin/NodeFormModal";
import ImportBookModal from "./admin/ImportBookModal";
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
  { key: "llm", label: "AI草稿" },
];

// 作者/作品/涟漪表默认按修改时间从新到旧排序(updatedAt 为 UTC ISO 字符串,字典序即时间序);其余 Tab 不默认排序
function defaultSortFor(k: AdminTab): { key: string; dir: 1 | -1 } | null {
  return k === "authors" || k === "works" || k === "edges" ? { key: "updatedAt", dir: -1 } : null;
}

function colsFor(isAdmin: boolean): Record<AdminTab, { key: string; label: string }[]> {
  const reviewCol = (label: string) => ({ key: "reviewStatus", label });
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
        ],
    works: isAdmin
      ? [
          { key: "Title_CN", label: "中文名" },
          { key: "originalTitle", label: "原著标题" },
          { key: "author_id", label: "作者" },
          { key: "readingStatus", label: "阅读状态" },
          { key: "recommendation", label: "评分" },
          reviewCol("审核状态"),
        ]
      : [
          { key: "Title_CN", label: "中文名" },
          { key: "originalTitle", label: "原著标题" },
          { key: "author_id", label: "作者" },
          { key: "readingStatus", label: "阅读状态" },
          { key: "recommendation", label: "评分" },
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
    llm: [],
  };
}

export default function Admin() {
  const { state, dispatch } = useApp();
  // 星云工坊对所有登录用户开放:非 admin 管理自己的空间(/api/me),
  // admin 管理自己的星云(/api/admin,即其名下星云);日志/快照仅 admin。
  const isAdmin = state.user?.role === "admin";
  const isVip = Boolean(state.user?.vip);
  const apiBase = isAdmin ? "/api/admin" : "/api/me";
  // AI 草稿页签:admin 与 VIP 均可审核自己上传的草稿
  const tabs = isAdmin || isVip ? KINDS : KINDS.filter((k) => k.key !== "llm");
  const [kind, setKind] = useState<AdminTab>("authors");
  const [data, setData] = useState<AdminData | null>(null);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const [confirmState, setConfirmState] = useState<{
    title: string;
    message: string;
    danger?: boolean;
    onConfirm: () => void;
  } | null>(null);
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(() => defaultSortFor("authors"));
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [textFilters, setTextFilters] = useState<Record<string, string>>({});
  const [warnings, setWarnings] = useState<AdminData["warnings"] | null>(null);
  // { mode: "add" | "edit", row: 表单初始值(编辑时为完整行) }
  const [modal, setModal] = useState<{ mode: "add" | "edit"; row: Partial<AdminRow> } | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  // AI 草稿页导入完成后,通过更换 key 强制 LlmDraftsPanel 重新加载
  const [llmReloadKey, setLlmReloadKey] = useState(0);

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

  const downloadBlob = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  // 导出自己星云的三张表(作者/作品/涟漪)为 CSV zip
  const exportCsv = () => {
    setStatus("正在导出…");
    authFetch(apiBase + "/export")
      .then((r) => {
        if (!r.ok) {
          handleAuthError(r);
          throw new Error("导出失败(" + r.status + ")");
        }
        const disposition = r.headers.get("Content-Disposition") || "";
        const m = disposition.match(/filename="?([^";]+)"?/);
        const name = m ? m[1] : "echo-graph-export.zip";
        return r.blob().then((b) => ({ blob: b, name }));
      })
      .then(({ blob, name }) => {
        downloadBlob(blob, name);
        setStatus("已导出:" + name);
      })
      .catch(() => setStatus("导出失败,请重试"));
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

  if (!state.adminOpen) return null;

  const allRows: AdminRow[] = data ? (data[kind as AdminKind] || []) : [];
  const cols = colsFor(isAdmin)[kind];
  const counts = data ? data.counts : undefined;

  // Tab 角标计数:日志/快照为特殊 Tab,避免对不存在的 data[k] 取值
  const tabCount = (k: AdminTab): string => {
    if (k === "llm") return "";
    const n = counts ? (counts as Record<AdminKind, number>)[k as AdminKind] : undefined;
    if (n != null) return String(n);
    return data ? String((data[k as AdminKind] || []).length) : "";
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
        llm: [],
        audit: [],
        snapshots: [],
      }
    : {
        authors: [
          { key: "nationality", type: "select" as const },
          { key: "Name_CN", type: "text" as const },
          { key: "originalName", type: "text" as const },
        ],
        works: [
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
        llm: [],
        audit: [],
        snapshots: [],
      }) as Record<AdminTab, { key: string; type: "select" | "text" }[]>;
  const uniqueValues = (key: string): string[] =>
    Array.from(
      new Set(allRows.map((r) => String((r as unknown as Record<string, unknown>)[key] || "")).filter(Boolean))
    ).sort((a, b) => a.localeCompare(b));

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

  const openEdit = (row: AdminRow) => {
    setModal({ mode: "edit", row });
  };

  // 乐观更新:成功后直接改本地 data,不再整页重拉(仅刷新同步状态)
  const applyLocal = (updater: (prev: AdminData) => AdminData) => {
    if (data) setData(updater(data));
  };

  // 数据写入后刷新星云图(仅当管理空间与当前浏览空间一致时才有意义:
  // admin 管理的是自己的星云,与「我的星云」同源)
  const refreshGraphAfterWrite = () => {
    const relevant = state.space === "mine";
    if (relevant) refreshSpaceGraph();
  };

  const doDelete = (row: AdminRow) => {
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
                [key]: (prev[key] || []).map((r: AdminRow) =>
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
            [key]: (prev[key] || []).map((r: AdminRow) =>
              r.id === id ? { ...r, deletedAt: null } : r
            ),
          }));
          refreshGraphAfterWrite();
        }
      })
      .catch((e) => setStatus("恢复失败: " + e.message));
  };

  // 永久删除:物理删除已软删除的行(不可恢复),级联清理关联数据
  const doPermanentDelete = (row: AdminRow) => {
    const id = row.id;
    setConfirmState({
      title: "确认永久删除",
      message: `将从数据库中彻底删除「${rowLabel(row)}」及其软删除的关联数据,不可恢复。确定继续吗?`,
      danger: true,
      onConfirm: () => {
        authFetch(apiBase + "/" + kind + "/" + encodeURIComponent(id) + "/permanent", { method: "DELETE" })
          .then((r) => r.json())
          .then((d) => {
            if (d.ok) {
              setStatus(`已永久删除「${rowLabel(row)}」`);
              const key = kind as "authors" | "works" | "edges";
              applyLocal((prev) => ({
                ...prev,
                [key]: (prev[key] || []).filter((r: AdminRow) => r.id !== id),
              }));
              refreshGraphAfterWrite();
            } else {
              setStatus(d.detail || "永久删除失败");
            }
          })
          .catch((e) => setStatus("永久删除失败: " + e.message));
      },
    });
  };

  // 行内直接修改阅读状态(只更新该字段,乐观锁带 updatedAt)
  const onReadingStatusChange = (row: AdminRow, value: string) => {
    const id = row.id;
    const patch = {
      readingStatus: value,
      updatedAt: (row as unknown as Record<string, unknown>).updatedAt,
    };
    authFetch(apiBase + "/works/" + encodeURIComponent(id), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    })
      .then((r) => r.json())
      .then((d) => {
        if (d.ok) {
          applyLocal((prev) => ({
            ...prev,
            works: (prev.works || []).map((w: WorkRow) =>
              w.id === id ? { ...w, readingStatus: value as WorkRow["readingStatus"] } : w
            ),
          }));
          setStatus("阅读状态已更新");
        } else {
          setStatus(d.detail || "更新失败");
        }
      })
      .catch((e) => setStatus("更新失败: " + e.message));
  };

  const worksList: WorkRow[] = data ? data.works || [] : [];
  const authorsList: AuthorRow[] = data ? data.authors || [] : [];
  const worksById: Record<string, WorkRow> = {};
  const authorsById: Record<string, AuthorRow> = {};
  worksList.forEach((w) => { worksById[w.id] = w; });
  authorsList.forEach((a) => { authorsById[a.id] = a; });

  // 行显示名(删除确认/状态提示用):作者名 / 作品标题 / 涟漪 A → B
  const rowLabel = (row: AdminRow): string => {
    if (kind === "authors") return authorLabelOf(row as AuthorRow);
    if (kind === "works") return workLabel(row as WorkRow);
    return edgeDisplayLabel(row as EdgeRow, worksById, workLabel);
  };

  // 单元格显示值(与表格渲染一致,排序/筛选共用)
  const cellValue = (r: AdminRow, key: string): string => {
    const rec = r as unknown as Record<string, unknown>;
    if (kind === "edges" && (key === "source_work_id" || key === "target_work_id")) {
      const wid = String(rec[key] ?? "");
      const w = worksById[wid];
      return w ? workLabel(w) : wid;
    }
    if (kind === "works" && key === "author_id") {
      return authorDisplayNames(r as WorkRow, authorsById, authorLabelOf);
    }
    if (key === "recommendation") {
      return rec[key] === "recommend" ? "推荐" : rec[key] === "not_recommend" ? "不推荐" : "";
    }
    if (key === "readingStatus") {
      return rec[key] === "read" ? "已读" : rec[key] === "reading" ? "在读" : rec[key] === "unread" ? "未读" : "";
    }
    const v = rec[key];
    return v == null ? "" : String(v);
  };

  return (
    <div id="admin-overlay">
      <div className="admin-shell">
        <div className="admin-head">
          <div className="admin-head-left">
            <h2 className="admin-title">星云工坊</h2>
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
            {(isAdmin || isVip) && <button onClick={() => setImportOpen(true)}>导入</button>}
            {kind !== "llm" && (
              <>
                <button onClick={openAdd}>＋ 新增</button>
                <button onClick={exportCsv}>导出 CSV</button>
              </>
            )}
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
          {kind === "llm" ? (
            <LlmDraftsPanel
              key={llmReloadKey}
              authFetch={authFetch}
              onStatus={setStatus}
              onPublicChanged={load}
            />
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
                  ? (
                    <>
                      <button onClick={() => doRestore(r.id)}>恢复</button>
                      <button className="del" onClick={() => doPermanentDelete(r)}>永久删除</button>
                    </>
                  )
                  : <button onClick={() => openEdit(r)}>编辑</button>
              }
              renderCell={(r, key) => {
                if (kind === "works" && key === "readingStatus") {
                  const rec = r as unknown as Record<string, unknown>;
                  if (rec.deletedAt) return cellValue(r, key);
                  return (
                    <select
                      className="admin-inline-select"
                      value={String(rec.readingStatus || "")}
                      onChange={(e) => onReadingStatusChange(r, e.target.value)}
                      title="直接修改阅读状态"
                    >
                      <option value="">—</option>
                      <option value="read">已读</option>
                      <option value="reading">在读</option>
                      <option value="unread">未读</option>
                    </select>
                  );
                }
                return cellValue(r, key);
              }}
            />
          )}
        </div>
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
          onWorkAdded={(row) => {
            applyLocal((prev) => ({ ...prev, works: [...(prev.works || []), row] }));
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
          onDelete={modal.mode === "edit" ? () => doDelete(modal.row as AdminRow) : undefined}
        />
      )}

      {importOpen && (
        <ImportBookModal
          authFetch={authFetch}
          onClose={() => setImportOpen(false)}
          onStatus={setStatus}
          onImported={() => setLlmReloadKey((k) => k + 1)}
        />
      )}
    </div>
  );
}


